"""
harness/verify.py
─────────────────
객관적 기능 검증 — "스위트가 녹색인가" 가 아니라
"이 기능을 검증하는 테스트가 존재하고 통과하는가" 를 판정한다.

배경 (TS-008):
  TS-006 의 증거 게이트는 `jest` 종료 코드만 봤다. 그래서 "스위트 녹색"은 보장했지만
  **그 스위트가 해당 기능을 검증한다는 보장은 전혀 없었다.** 실측 결과:
    - F-015 (`passes: true`) — 순위표 구현도 테스트도 전무. 완전한 거짓 통과.
    - F-018 (`passes: false`) — 명세 2단계를 모두 검증하는 테스트가 있는데 미완성 표시.
  플래그가 양방향으로 틀렸다. 스위트가 녹색이어도 이 둘은 구분되지 않는다.

판정 기준의 근거 — 임의로 만든 규약이 아니다:
  `web_target/tests/LoginForm.test.tsx` 는 이미
    describe("F-001: 이메일/비밀번호 로그인")
    describe("F-002: 잘못된 자격증명 오류 처리")
    describe("F-003: 이메일 형식 유효성 검사")
  형태로 **기능 ID 를 테스트 이름에 박아 왔다.** 이 모듈은 새 기준을 발명하는 대신
  프로젝트가 이미 쓰던 규약을 기계가 강제하도록 만든다. 따라서 기준은
  "사람이 정한 가중치" 가 아니라 **"명세 ID 를 인용하는 통과 테스트의 존재"** 라는
  재현 가능한 사실이다.

검증 수준 (config.EVIDENCE_LEVEL):
  suite    — 스위트 녹색만 (TS-006 동작. 하위 호환용)
  feature  — 스위트 녹색 + 기능 ID 태그 테스트 1개 이상 전부 통과  ← 기본값
  step     — feature + 명세 steps 각각에 대응하는 태그 테스트 통과 (최고 엄격도)

  step 커버리지는 수준과 무관하게 **항상 측정해 보고한다** — 강제하지 않더라도
  어느 단계가 검증되지 않았는지는 기록에 남아야 한다.

태그 표기:
  기능  — 이름 어디든 `F-004` (단어 경계. `F-0041` 은 매칭되지 않는다)
  단계  — `F-004.5` / `F-004-5` / `F-004#5` (1-기반 인덱스)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config

#: 검증 수준 — 엄격도 오름차순
LEVELS = ("suite", "feature", "step")

#: 기록에 남길 증거 테스트 이름 최대 개수
MAX_EVIDENCE_NAMES = 20


# ── jest 실행 ────────────────────────────────────────────────────────────────

def jest_launcher(project_root: str) -> list[str] | None:
    """jest 를 실행할 커맨드 접두사를 반환한다. 없으면 None.

    Windows 주의 (TS-006): `subprocess.run(["npx", ...])` 는 shell=False 에서
    `npx.cmd` 를 찾지 못해 항상 FileNotFoundError 를 던진다. PATHEXT 를 처리하는
    shutil.which 를 쓰고, 프로젝트 로컬 바이너리를 우선한다.
    절대 경로 필수 — subprocess 가 cwd=project_root 로 전환하므로 상대 경로는 깨진다.
    """
    root = Path(project_root).resolve()

    bin_dir = root / "node_modules" / ".bin"
    for name in ("jest.cmd", "jest.CMD", "jest"):
        candidate = bin_dir / name
        if candidate.is_file():
            return [str(candidate)]

    # npx 폴백은 **대상이 실제로 jest 를 설정한 JS 프로젝트일 때만** 쓴다 (TS-008).
    # 근거: jest 는 설정을 못 찾으면 상위 디렉터리로 올라가며 rootDir 을 추정한다.
    # 빈 디렉터리에서 실행했을 때 rootDir 이 **사용자 홈**으로 잡혀 .vscode/extensions
    # 전체를 스캔하며 2분 타임아웃까지 멈추는 것을 실측했다. 전제조건 없이 npx 로
    # 폴백하면 '테스트 0건'이 아니라 '사용자 홈 스캔'이 된다.
    # 또한 --no-install 로 네트워크 설치 시도를 차단한다 (남의 레포 오염 방지).
    if not _has_jest_config(root):
        return None
    npx = shutil.which("npx")
    if npx:
        return [npx, "--no-install", "jest"]
    return None


def _has_jest_config(root: Path) -> bool:
    """대상 프로젝트가 jest 설정을 갖고 있는지 확인한다 (상위 디렉터리는 보지 않는다)."""
    for name in ("jest.config.ts", "jest.config.js", "jest.config.mjs",
                 "jest.config.cjs", "jest.config.json"):
        if (root / name).is_file():
            return True
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        return isinstance(data, dict) and "jest" in data
    return False


def run_jest(
    project_root: str,
    test_path: str = ".",
    coverage: bool = False,
) -> tuple[int | None, str]:
    """사람이 읽을 출력을 위한 jest 실행. (종료코드, 출력). None = 실행 불가."""
    launcher = jest_launcher(project_root)
    if launcher is None:
        return None, (
            "[오류] jest 실행 파일을 찾을 수 없습니다. "
            f"{project_root} 에서 npm install 을 먼저 실행하십시오."
        )

    flags = ["--no-coverage"] if not coverage else ["--coverage", "--coverageReporters=text"]
    timeout = config.TOOL_TIMEOUTS.get("run_tests", 120)
    try:
        result = subprocess.run(
            [*launcher, test_path, "--rootDir", str(Path(project_root).resolve()), *flags],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return None, f"[오류] 테스트 타임아웃 ({timeout}초)"
    except FileNotFoundError:
        return None, "[오류] Jest를 찾을 수 없습니다. npm install을 먼저 실행하십시오."


def run_jest_json(project_root: str) -> tuple[dict[str, Any] | None, str]:
    """jest 를 `--json` 으로 실행해 구조화된 결과를 반환한다.

    Returns:
        (결과 dict, 진단 메시지). dict 가 None 이면 실행/파싱 실패.

    테스트가 실패해도 jest 는 JSON 을 쓴다(종료 코드만 1). 따라서 종료 코드와
    무관하게 파일을 읽는다 — 실패 내역 자체가 판정에 필요한 증거다.
    결과 파일은 임시 디렉터리에 쓴다 (대상 레포를 오염시키지 않는다).
    """
    launcher = jest_launcher(project_root)
    if launcher is None:
        return None, (
            "[오류] jest 실행 파일을 찾을 수 없습니다. "
            f"{project_root} 에서 npm install 을 먼저 실행하십시오."
        )

    timeout = config.TOOL_TIMEOUTS.get("run_tests", 120)
    tmp_dir = tempfile.mkdtemp(prefix="harness-jest-")
    out_path = Path(tmp_dir) / "results.json"
    try:
        subprocess.run(
            [*launcher, ".", "--rootDir", str(Path(project_root).resolve()),
             "--no-coverage", "--json", f"--outputFile={out_path}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"[오류] 테스트 타임아웃 ({timeout}초)"
    except FileNotFoundError:
        return None, "[오류] Jest를 찾을 수 없습니다. npm install을 먼저 실행하십시오."

    if not out_path.is_file():
        return None, "[오류] jest 가 결과 JSON 을 생성하지 않았습니다."
    try:
        return json.loads(out_path.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return None, f"[오류] jest 결과 JSON 파싱 실패: {exc}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── 태그 매칭 ────────────────────────────────────────────────────────────────

def feature_tag_pattern(feature_id: str) -> re.Pattern[str]:
    """기능 ID 를 단어 경계로 매칭한다. `F-004` 는 `F-0041` 에 매칭되지 않는다."""
    return re.compile(rf"(?<![\w-]){re.escape(feature_id)}(?![\w-])")


def step_tag_pattern(feature_id: str, step_index: int) -> re.Pattern[str]:
    """`F-004.5` / `F-004-5` / `F-004#5` 형태의 단계 태그를 매칭한다 (1-기반)."""
    return re.compile(
        rf"(?<![\w-]){re.escape(feature_id)}[.#-]0*{step_index}(?![\d])"
    )


def iter_assertions(results: dict[str, Any]):
    """jest JSON 에서 (전체이름, 상태) 를 순회한다."""
    for suite in results.get("testResults", []) or []:
        for assertion in suite.get("assertionResults", []) or []:
            full = assertion.get("fullName")
            if not full:
                ancestors = assertion.get("ancestorTitles") or []
                full = " ".join([*ancestors, assertion.get("title", "")]).strip()
            yield full, assertion.get("status", "unknown")


# ── 판정 결과 ────────────────────────────────────────────────────────────────

@dataclass
class Verification:
    """기능 하나에 대한 검증 결과. features.json 에 그대로 기록된다."""

    ok: bool
    level: str
    reason: str = ""
    suite: dict[str, int] = field(default_factory=dict)
    tagged_passed: list[str] = field(default_factory=list)
    tagged_failed: list[str] = field(default_factory=list)
    steps_covered: list[int] = field(default_factory=list)
    steps_uncovered: list[int] = field(default_factory=list)

    def summary(self) -> str:
        """한 줄 요약."""
        s = self.suite
        core = (
            f"suite {s.get('passed', 0)}/{s.get('total', 0)} passed"
            f" | tagged {len(self.tagged_passed)} passed"
        )
        if self.tagged_failed:
            core += f", {len(self.tagged_failed)} failed"
        if self.steps_covered or self.steps_uncovered:
            total = len(self.steps_covered) + len(self.steps_uncovered)
            core += f" | steps {len(self.steps_covered)}/{total} covered"
        return core

    def to_dict(self) -> dict[str, Any]:
        """features.json 에 기록할 증거 블록."""
        data: dict[str, Any] = {
            "level":   self.level,
            "suite":   self.suite,
            "summary": self.summary(),
            "evidence_tests": self.tagged_passed[:MAX_EVIDENCE_NAMES],
        }
        if len(self.tagged_passed) > MAX_EVIDENCE_NAMES:
            data["evidence_tests_omitted"] = len(self.tagged_passed) - MAX_EVIDENCE_NAMES
        if self.steps_covered or self.steps_uncovered:
            data["steps_covered"] = self.steps_covered
            if self.steps_uncovered:
                data["steps_uncovered"] = self.steps_uncovered
        return data


# ── 메인 판정 ────────────────────────────────────────────────────────────────

def verify_feature(
    project_root: str,
    feature: dict[str, Any],
    level: str | None = None,
    results: dict[str, Any] | None = None,
) -> Verification:
    """기능 하나가 '통과' 로 기록될 자격이 있는지 판정한다.

    Args:
        project_root: 대상 프로젝트 루트
        feature:      features.json 의 항목 (id / description / steps)
        level:        suite | feature | step (기본: config.EVIDENCE_LEVEL)
        results:      이미 확보한 jest JSON (재사용 시). None 이면 직접 실행한다.

    Returns:
        Verification — ok=False 면 reason 에 거부 사유가 담긴다.
    """
    level = (level or getattr(config, "EVIDENCE_LEVEL", "feature")).lower()
    if level not in LEVELS:
        level = "feature"

    feature_id = str(feature.get("id", "")).strip()

    if results is None:
        results, diag = run_jest_json(project_root)
        if results is None:
            return Verification(ok=False, level=level, reason=diag)

    suite_stats = {
        "total":  int(results.get("numTotalTests", 0)),
        "passed": int(results.get("numPassedTests", 0)),
        "failed": int(results.get("numFailedTests", 0)),
        "suites_total":  int(results.get("numTotalTestSuites", 0)),
        "suites_failed": int(results.get("numFailedTestSuites", 0)),
    }

    assertions = list(iter_assertions(results))

    # 기능 태그 수집 — 수준과 무관하게 항상 측정한다
    tagged_passed: list[str] = []
    tagged_failed: list[str] = []
    if feature_id:
        pattern = feature_tag_pattern(feature_id)
        for name, status in assertions:
            if pattern.search(name):
                (tagged_passed if status == "passed" else tagged_failed).append(name)

    # 단계 커버리지 — 역시 항상 측정해 기록한다
    steps = feature.get("steps") or []
    covered: list[int] = []
    uncovered: list[int] = []
    if feature_id and steps:
        for idx in range(1, len(steps) + 1):
            spat = step_tag_pattern(feature_id, idx)
            hit = any(
                spat.search(name) and status == "passed"
                for name, status in assertions
            )
            (covered if hit else uncovered).append(idx)

    verification = Verification(
        ok=False,
        level=level,
        suite=suite_stats,
        tagged_passed=tagged_passed,
        tagged_failed=tagged_failed,
        steps_covered=covered,
        steps_uncovered=uncovered,
    )

    # ── 판정 ────────────────────────────────────────────────────────────────
    # 1) 회귀: 스위트가 빨간불이면 어떤 수준에서도 통과 불가
    if suite_stats["failed"] > 0:
        verification.reason = (
            f"스위트에 실패 테스트 {suite_stats['failed']}건 — "
            "다른 기능을 깨뜨린 상태에서는 통과로 기록할 수 없습니다."
        )
        return verification

    if suite_stats["total"] == 0:
        verification.reason = "테스트가 0건입니다 — 증거가 존재할 수 없습니다."
        return verification

    if level == "suite":
        verification.ok = True
        return verification

    # 2) 기능 수준: 이 기능 ID 를 인용하는 통과 테스트가 있어야 한다
    if not feature_id:
        verification.reason = "기능 항목에 id 가 없어 태그를 검증할 수 없습니다."
        return verification

    if tagged_failed:
        verification.reason = (
            f"{feature_id} 태그 테스트 {len(tagged_failed)}건 실패: "
            + "; ".join(tagged_failed[:3])
        )
        return verification

    if not tagged_passed:
        verification.reason = (
            f"{feature_id} 를 검증하는 테스트가 없습니다. "
            f"스위트는 녹색이지만 그것은 이 기능의 증거가 아닙니다. "
            f"테스트 이름에 기능 ID 를 넣으십시오 "
            f'(예: describe("{feature_id}: {str(feature.get("description", ""))[:30]}", ...)).'
        )
        return verification

    if level == "feature":
        verification.ok = True
        return verification

    # 3) 단계 수준: 명세의 모든 단계가 태그된 통과 테스트로 덮여야 한다
    if uncovered:
        verification.reason = (
            f"{feature_id} 의 명세 단계 {uncovered} 가 검증되지 않았습니다. "
            f'단계 태그를 사용하십시오 (예: test("{feature_id}.{uncovered[0]} ...")).'
        )
        return verification

    verification.ok = True
    return verification


def audit_features(
    project_root: str,
    features: list[dict[str, Any]],
    level: str | None = None,
) -> list[tuple[dict[str, Any], Verification]]:
    """여러 기능을 **jest 한 번만 실행해서** 일괄 재검증한다.

    `passes: true` 로 기록된 항목들이 지금 기준으로도 자격이 있는지 감사할 때 쓴다.
    """
    results, diag = run_jest_json(project_root)
    if results is None:
        level = (level or getattr(config, "EVIDENCE_LEVEL", "feature")).lower()
        return [(f, Verification(ok=False, level=level, reason=diag)) for f in features]
    return [
        (f, verify_feature(project_root, f, level=level, results=results))
        for f in features
    ]

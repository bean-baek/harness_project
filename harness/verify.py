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


# ── 증거가 실제로 소스를 실행하는가 (TS-016) ─────────────────────────────────
#
# TS-008 이후 증거는 "기능 ID 를 인용하는 통과 테스트"다. 그런데 **그 테스트가 아무것도
# 실행하지 않아도 통과한다** — `test('F-006: x', () => expect(true).toBe(true))` 는
# 완벽한 증거로 계수된다. 게이트는 이름만 보기 때문이다 (TS-008 이 남긴 주관성).
#
# 커버리지는 그 공백을 **정확하게** 막는다: 태그 테스트만 실행했을 때 비(非)테스트 소스를
# 한 줄도 덮지 않으면 그 증거는 공허하다. 휴리스틱이 아니라 사실 판정이다.
#
# 비용 때문에 호출 위치가 중요하다. 기능별 커버리지는 jest 를 한 번 더 돌려야 하므로(약 9초)
# `verify_feature` 안에 넣으면 `audit`/`report` 가 수십~수백 배 느려진다
# (discrimination_report 는 75기능 × 3수준을 판정한다). 그래서 **플래그를 쓰는 순간**
# (apply_flag)에만 수행한다 — 기능당 한 번이다.

def feature_name_pattern(feature_id: str) -> str:
    """jest --testNamePattern 용 정규식. `F-005` 가 `F-0051` 에 걸리지 않게 한다."""
    return f"{re.escape(feature_id)}(?![0-9])"


def tagged_test_files(project_root: str, feature_id: str) -> list[str]:
    """해당 기능 태그가 있는 **단위 테스트 파일** 목록 (jest 범위 제한용)."""
    from harness.tags import scan_tags
    files = {
        ref.file for ref in scan_tags(project_root)
        if ref.feature_id == feature_id and ref.kind == "unit"
    }
    return sorted(files)


def coverage_for_feature(
    project_root: str,
    feature_id: str,
    top_n: int = 5,
    test_files: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """해당 기능의 태그 테스트만 실행해 어떤 소스를 덮는지 측정한다.

    Returns:
        ({covered_statements, sources, files_touched}, 진단). 첫 값이 None 이면 측정 실패.

    **파일 범위까지 제한해야 한다.** `--testNamePattern` 은 테스트 *실행*만 건너뛰고
    테스트 파일은 전부 import 한다. 그래서 다른 파일들의 모듈 수준 import 가
    커버리지에 섞여, 아무것도 실행하지 않는 공허한 테스트가 42 statements 를 덮은 것처럼
    집계됐다(실측). 태그가 있는 파일만 인자로 넘겨 그 오염을 제거한다.

    주의: 부분 실행이므로 전역 커버리지 임계(80%)를 반드시 끈다 — 끄지 않으면
    임계 미달로 비정상 종료해 측정 자체가 실패한 것처럼 보인다.
    """
    launcher = jest_launcher(project_root)
    if launcher is None:
        return None, "[오류] jest 실행 파일을 찾을 수 없습니다."

    if test_files is None:
        test_files = tagged_test_files(project_root, feature_id)
    if not test_files:
        return None, f"[오류] {feature_id} 태그가 있는 단위 테스트 파일이 없습니다."

    root = Path(project_root).resolve()
    tmp_dir = tempfile.mkdtemp(prefix="harness-cov-")
    timeout = config.TOOL_TIMEOUTS.get("run_tests", 120)
    try:
        subprocess.run(
            [
                *launcher,
                *test_files,
                "--rootDir", str(root),
                "--testNamePattern", feature_name_pattern(feature_id),
                "--coverage",
                "--coverageReporters=json-summary",
                f"--coverageDirectory={tmp_dir}",
                "--coverageThreshold={}",
            ],
            cwd=project_root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        summary_path = Path(tmp_dir) / "coverage-summary.json"
        if not summary_path.is_file():
            return None, "[오류] 커버리지 요약이 생성되지 않았습니다."
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return None, f"[오류] 커버리지 측정 타임아웃 ({timeout}초)"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"[오류] 커버리지 측정 실패: {exc}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    hits: list[tuple[str, int]] = []
    for path, metrics in data.items():
        if path == "total":
            continue
        covered = int(metrics.get("statements", {}).get("covered", 0))
        if covered <= 0:
            continue
        name = Path(path).name
        # 테스트 파일 자신은 증거가 아니다
        if name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
            continue
        hits.append((name, covered))

    hits.sort(key=lambda h: -h[1])
    return {
        "covered_statements": sum(c for _, c in hits),
        "files_touched": len(hits),
        "sources": [f"{n} ({c})" for n, c in hits[:top_n]],
    }, ""


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


# ── features.json 읽기/쓰기 + 게이트 적용 ───────────────────────────────────
# 게이트 정책은 이 모듈이 **유일하게** 소유한다. langchain 도구(`tools.update_features`)와
# 토큰 없는 CLI(`harness.cli`)가 같은 함수를 호출하므로 구현이 갈라지지 않는다.

def features_path(project_root: str) -> Path:
    return Path(project_root) / "features.json"


def load_features(project_root: str) -> list[dict[str, Any]]:
    """features.json 을 읽는다. 없으면 FileNotFoundError."""
    return json.loads(features_path(project_root).read_text(encoding="utf-8"))


def save_features(project_root: str, features: list[dict[str, Any]]) -> None:
    features_path(project_root).write_text(
        json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def find_index(features: list[dict[str, Any]], feature_id: str) -> int:
    """기능 ID 로 인덱스를 찾는다. 없으면 -1."""
    for i, f in enumerate(features):
        if str(f.get("id", "")).strip().upper() == feature_id.strip().upper():
            return i
    return -1


def apply_flag(
    project_root: str,
    feature_index: int,
    passes: bool,
    require_evidence: bool | None = None,
) -> tuple[bool, str]:
    """features.json 의 통과 플래그를 **증거 게이트를 통과한 경우에만** 쓴다.

    Returns:
        (적용 여부, 사람이 읽을 메시지)

    passes=True  → 전체 스위트 실행 + 기능 ID 태그 통과 테스트 요구 (TS-008)
    passes=False → 증거 없이 허용하고 과거 증거를 제거한다
    """
    from datetime import datetime

    if require_evidence is None:
        require_evidence = getattr(config, "REQUIRE_TEST_EVIDENCE", True)

    path = features_path(project_root)
    if not path.exists():
        return False, "[오류] features.json이 없습니다."
    features = load_features(project_root)
    if feature_index < 0 or feature_index >= len(features):
        return False, f"[오류] 인덱스 {feature_index}가 범위를 벗어났습니다."

    feature = features[feature_index]
    name = feature.get("description", f"Feature #{feature_index}")
    old_status = feature.get("passes", False)
    verification: dict[str, Any] | None = None

    if passes and require_evidence:
        result = verify_feature(project_root, feature)
        if not result.ok:
            return False, (
                f"[거부] '{name}': passes=true 를 반영하지 않았습니다.\n"
                f"사유: {result.reason}\n"
                f"현황: {result.summary()}"
            )
        verification = {
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "verified_by": "update_features/jest",
            **result.to_dict(),
        }

        # 증거가 실제로 소스를 실행하는지 확인한다 (TS-016).
        # 여기서만 수행한다 — 기능당 한 번. verify_feature 안에 넣으면 audit/report 가 멈춘다.
        if getattr(config, "REQUIRE_EVIDENCE_COVERAGE", True):
            cov, diag = coverage_for_feature(project_root, str(feature.get("id", "")))
            if cov is None:
                return False, (
                    f"[거부] '{name}': 증거 커버리지를 측정할 수 없어 반영하지 않았습니다.\n"
                    f"사유: {diag}"
                )
            if cov["covered_statements"] <= 0:
                return False, (
                    f"[거부] '{name}': 태그 테스트가 **소스를 한 줄도 실행하지 않습니다**.\n"
                    f"사유: 이름만 맞는 공허한 증거입니다 "
                    f"(예: expect(true).toBe(true)). 실제 구현을 호출하는 테스트가 필요합니다."
                )
            verification["evidence_sources"] = cov["sources"]
            verification["covered_statements"] = cov["covered_statements"]
            verification["summary"] += f" | 소스 {cov['covered_statements']} statements 실행"

    feature["passes"] = passes
    if verification:
        feature["verification"] = verification
    elif not passes:
        feature.pop("verification", None)

    save_features(project_root, features)

    evidence = f" (증거: {verification['summary']})" if verification else ""
    if passes and not require_evidence:
        evidence = " ⚠ 증거 게이트가 비활성(HARNESS_REQUIRE_TEST_EVIDENCE=false)"
    return True, f"[완료] '{name}': {old_status} → {passes}{evidence}"


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

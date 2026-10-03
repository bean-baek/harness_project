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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from harness import project
from harness import runner as runner_mod
from harness.project import ProjectConfig
from harness.runner import Runner

#: 검증 수준 — 엄격도 오름차순
LEVELS = ("suite", "feature", "step")

#: 기록에 남길 증거 테스트 이름 최대 개수
MAX_EVIDENCE_NAMES = 20


# ── 런너 위임 ────────────────────────────────────────────────────────────────
#
# 생태계에 묶인 부분은 전부 `harness/runner.py` 로 옮겼다. 이 모듈에 남은 것은
# **판정 정책**이며 jest·vitest·pytest 어디서든 같다.
#
# 공개 이름(`jest_launcher`/`run_jest`/`run_jest_json`/`coverage_for_feature`)은
# 유지한다 — 재현 스크립트 7종이 이 이름들을 스텁으로 교체해 LLM·jest 없이 게이트를
# 검증하기 때문이다. 이름을 바꾸면 236개 검증의 격리가 무너진다.
#
# `.harness.json` 이 없으면 `ProjectConfig()` 의 기본값이 쓰이고, 그 기본값은
# 이 리팩터 이전의 하드코딩과 **같은 값**이다 (jest / .test.ts,.tsx / .spec.ts,.tsx).
# 따라서 설정 파일을 추가하지 않은 프로젝트의 동작은 변하지 않는다.

def config_for(project_root: str) -> ProjectConfig:
    """대상 경로에 적용할 설정 (`harness.project.config_for` 위임)."""
    return project.config_for(project_root, config.BASE_DIR)


def runner_for(project_root: str) -> Runner:
    """대상 경로의 테스트 런너."""
    return runner_mod.for_project(config_for(project_root), config.BASE_DIR)


def jest_launcher(project_root: str) -> list[str] | None:
    """런너 실행 커맨드 접두사. 없으면 None.

    이름은 역사적이다(jest 전용이던 시절). 지금은 선언된 런너에 위임한다.
    """
    try:
        return runner_for(project_root).launcher()
    except ValueError:
        return None


def run_jest(
    project_root: str,
    test_path: str = ".",
    coverage: bool = False,
) -> tuple[int | None, str]:
    """사람이 읽을 출력을 위한 전체 실행. (종료코드, 출력). None = 실행 불가."""
    try:
        return runner_for(project_root).run_all(test_path, coverage)
    except ValueError as exc:
        return None, f"[오류] {exc}"


def run_jest_json(project_root: str) -> tuple[dict[str, Any] | None, str]:
    """구조화된 테스트 결과를 **jest JSON 모양으로** 반환한다.

    런너가 무엇이든 이 모양으로 정규화한다. 하위 호환을 위해 dict 를 유지한다 —
    `verify_feature(results=...)` 와 재현 스크립트 스텁이 이 모양을 전제한다.
    """
    try:
        results, diag = runner_for(project_root).results()
    except ValueError as exc:
        return None, f"[오류] {exc}"
    if results is None:
        return None, diag
    return {
        "numTotalTests":      results.total,
        "numPassedTests":     results.passed,
        "numFailedTests":     results.failed,
        "numTotalTestSuites": results.suites_total,
        "numFailedTestSuites": results.suites_failed,
        "testResults": [{
            "name": "(normalized)",
            "assertionResults": [
                {"fullName": name, "title": name, "ancestorTitles": [], "status": status}
                for name, status in results.assertions
            ],
        }],
    }, ""


# ── 증거가 실제로 소스를 실행하는가 (TS-016) ─────────────────────────────────
#
# TS-008 이후 증거는 "기능 ID 를 인용하는 통과 테스트"다. 그런데 **그 테스트가 아무것도
# 실행하지 않아도 통과한다** — `test('F-006: x', () => expect(true).toBe(true))` 는
# 완벽한 증거로 계수됐다. 게이트는 이름만 보기 때문이다 (TS-008 이 남긴 주관성).
#
# 커버리지는 그 공백을 **정확하게** 막는다: 태그 테스트만 실행했을 때 비(非)테스트 소스를
# 한 줄도 덮지 않으면 그 증거는 공허하다. 휴리스틱이 아니라 사실 판정이다.
#
# 비용 때문에 호출 위치가 중요하다. 기능별 커버리지는 런너를 한 번 더 돌려야 하므로(약 9초)
# `verify_feature` 안에 넣으면 `audit`/`report` 가 수십~수백 배 느려진다
# (discrimination_report 는 75기능 × 3수준을 판정한다). 그래서 **플래그를 쓰는 순간**
# (apply_flag)에만 수행한다 — 기능당 한 번이다.

def feature_name_pattern(feature_id: str) -> str:
    """`--testNamePattern` 용 정규식. `F-005` 가 `F-0051` 에 걸리지 않게 한다."""
    return f"{re.escape(feature_id)}(?![0-9])"


def tagged_test_files(project_root: str, feature_id: str) -> list[str]:
    """해당 기능 태그가 있는 **단위 테스트 파일** 목록 (실행 범위 제한용).

    E2E 는 제외한다 — 런너가 다르므로 게이트 증거로 계수하지 않는다.
    어느 접미사가 단위/E2E 인지는 `.harness.json` 이 정한다.
    """
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
        **측정 실패는 통과가 아니다** — 호출자(apply_flag)는 거부로 처리한다.

    범위 제한의 근거는 `runner.coverage()` 의 docstring 에 있다 (TS-016 함정 2).
    """
    if test_files is None:
        test_files = tagged_test_files(project_root, feature_id)
    if not test_files:
        return None, f"[오류] {feature_id} 태그가 있는 단위 테스트 파일이 없습니다."

    try:
        cov, diag = runner_for(project_root).coverage(
            test_files, feature_name_pattern(feature_id)
        )
    except ValueError as exc:
        return None, f"[오류] {exc}"
    if cov is None:
        return None, diag

    return {
        "covered_statements": cov.total(),
        "files_touched": len(cov.per_file),
        "sources": cov.top(top_n),
        # 실행된 **줄 번호**. 돌연변이가 미실행 줄을 고르지 않게 하는 데 쓴다 (TS-026).
        # 비어 있으면 '줄 지도를 못 얻었다'이며 '실행된 줄이 없다'가 아니다 —
        # `mutate` 가 그 둘을 구분해 전자는 경고와 함께 진행하고 후자는 건너뛴다.
        "executed_lines": cov.executed_lines,
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
    """명세 파일 경로. `.harness.json` 의 spec 이 정한다 (기본 features.json).

    대상 루트에서 먼저 찾고 없으면 하네스 루트에서 찾는다 — 이 레포는 명세를
    하네스 루트에 두고 앱을 web_target/ 에 두는 배치이기 때문이다. 둘 다 없으면
    대상 루트의 경로를 반환한다 (생성 위치가 되고, 읽기는 FileNotFoundError).
    """
    cfg = config_for(project_root)
    spec = Path(cfg.spec)
    if spec.is_absolute():
        return spec
    root = Path(project_root)
    here = root / spec
    if here.is_file():
        return here
    sibling = (Path(config.BASE_DIR) / spec)
    if sibling.is_file():
        return sibling
    return here


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
            verification["summary"] += (
                f" | 소스 {cov['covered_statements']} statements 실행"
            )

        # ── 증거가 결함을 **감지하는가** (TS-021) ─────────────────────────────
        #
        # 커버리지는 "소스를 실행한다"까지만 보장한다. 실행하면서 아무것도 단정하지
        # 않는 테스트는 여전히 통과한다. 그걸 묻는 유일한 방법은 결함을 넣어보는 것이다.
        #
        # 기준은 **"유효한 변이 1개 이상을 잡는다"** — TS-016 의 "소스 1줄 이상 실행"과
        # 같은 모양의 최솟값이다. 비율(예: 80%)을 쓰지 않는 이유: 변이 대상을 커버리지로
        # 고르므로 다른 기능이 소유한 파일이 섞이고, 그 혼합에 비율을 적용하면
        # `EVAL_WEIGHTS` 와 같은 근거 없는 상수가 된다. 점수와 귀속은 보고에 남긴다.
        #
        # 기본값이 false 인 이유: 기능당 약 27초다 (실측). 켜면 `mark` 가 그만큼 느려진다.
        if getattr(config, "REQUIRE_MUTATION_EVIDENCE", False):
            from harness.mutate import mutate_feature

            report = mutate_feature(project_root, str(feature.get("id", "")))
            if "error" in report:
                # 도구가 돌지 않은 것은 '통과'가 아니다 (TS-016 의 규칙)
                return False, (
                    f"[거부] '{name}': 돌연변이를 측정할 수 없어 반영하지 않았습니다.\n"
                    f"사유: {report['error']}"
                )
            attempted = report["killed"] + report["survived"] + report["invalid"]
            if attempted == 0:
                # **측정 실패가 아니라 측정 대상 부재**다. 변이할 구문이 없는 코드는
                # 있을 수 있고(상수 선언만 있는 모듈 등), 그것을 거부하면 거짓 거부가 된다.
                # 도구 고장(위의 error)과 구분해 기록만 남긴다.
                #
                # 대상 부재의 **두 가지 이유를 구분한다** (TS-026):
                #   (a) 변이할 구문이 아예 없다 — 상수 선언만 있는 모듈
                #   (b) 구문은 있는데 **증거가 그 줄을 지나가지 않는다**
                # 둘을 같은 문구로 기록하면 나중에 읽는 사람이 (b) 를 (a) 로 읽는다.
                # (b) 를 거부하지 않는 이유: 커버리지 게이트가 이미 '소스 1줄 이상
                # 실행'을 요구했으므로 증거는 어딘가에 닿았고, 그 줄이 변이 가능한
                # 구문이 아닐 수 있다 — 그것은 결함이 아니다.
                unexec = report.get("skipped_unexecuted") or 0
                if unexec:
                    reason = (
                        f"변이 가능한 구문은 {unexec}곳 있으나 **증거가 그 줄을 "
                        f"하나도 지나가지 않습니다** — 테스트의 단정이 약한 것이 아니라 "
                        f"도달하지 않는 것입니다 (TS-026)"
                    )
                else:
                    reason = "변이를 적용할 구문이 없습니다 (비교·논리·조건·불리언 없음)"
                verification["mutation"] = {
                    "measured": False,
                    "reason": reason,
                    "unreached_sites": unexec,
                }
            elif report["killed"] <= 0:
                return False, (
                    f"[거부] '{name}': 태그 테스트가 **주입한 결함을 하나도 잡지 못했습니다**.\n"
                    f"사유: 유효한 변이 {report['killed'] + report['survived']}건 중 "
                    f"잡음 0건 — 소스를 실행하지만 단정하지 않는 증거입니다.\n"
                    f"현황: {', '.join(report['sources'])}"
                )
            else:
                verification["mutation"] = {
                    "measured": True,
                    "killed": report["killed"],
                    "survived": report["survived"],
                    "invalid": report["invalid"],
                    "score": report["score"],
                    "targets": report["sources"],
                    # 점수와 **그 점수가 무엇을 뺀 값인지**를 같이 적는다 (TS-026).
                    # 미실행 줄을 분모에서 빼면 점수가 올라가므로, 뺀 사실을 함께
                    # 기록하지 않으면 저장된 수치가 실제보다 좋아 보인다 (TS-024 의 모양).
                    "unreached_sites": report.get("skipped_unexecuted") or 0,
                    "unmapped_files": report.get("unmapped_files") or [],
                }

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

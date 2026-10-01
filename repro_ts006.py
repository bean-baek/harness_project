"""
TS-006 검증 스크립트
────────────────────
update_features(passes=True) 의 테스트 증거 게이트를 검증한다.

  1) 테스트 실패 → 플래그 거부, features.json 무변경
  2) 테스트 통과 → 플래그 반영 + verification 증거 기록
  3) 테스트 실행 불가(타임아웃/jest 없음) → 거부
  4) passes=False → 증거 없이 허용 + 과거 증거 제거
  5) REQUIRE_TEST_EVIDENCE=false(운영자 우회) → 경고와 함께 허용
  6) 게이트는 test_path 를 "." 로 고정 — 에이전트가 쉬운 테스트만 골라 돌릴 수 없다

Jest 는 스텁으로 대체한다 (_run_jest 를 교체). 실제 스위트 실행은 E2E 단계에서 따로 확인.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

import config
from harness import tools

ok = 0
fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


RED = """
  ● UserMenu › 로그아웃 버튼을 클릭하면 logout 함수가 호출된다
  ● UserMenu › 메뉴를 열고 닫을 수 있다
Test Suites: 1 failed, 4 passed, 5 total
Tests:       2 failed, 25 passed, 27 total
"""

GREEN = """
Test Suites: 5 passed, 5 total
Tests:       27 passed, 27 total
"""


def fresh_project() -> Path:
    """임시 features.json 을 가진 프로젝트 루트를 만든다."""
    root = Path(tempfile.mkdtemp(prefix="ts006-"))
    features = [
        {"id": "F-001", "description": "로그인", "passes": True},
        {"id": "F-004", "description": "로그아웃", "passes": False},
    ]
    (root / "features.json").write_text(
        json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root


def read_feature(root: Path, index: int) -> dict:
    return json.loads((root / "features.json").read_text(encoding="utf-8"))[index]


def stub_jest(returncode, output, record=None):
    """_run_jest 를 교체하고, 호출 인자를 record 리스트에 남긴다."""
    def _stub(project_root, test_path=".", coverage=False):
        if record is not None:
            record.append({"project_root": project_root, "test_path": test_path, "coverage": coverage})
        return returncode, output
    tools._run_jest = _stub


original_run_jest = tools._run_jest
original_flag = config.REQUIRE_TEST_EVIDENCE

try:
    print("\n[1] 테스트 실패 → passes=true 거부")
    root = fresh_project()
    calls = []
    stub_jest(1, RED, calls)
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("거부 메시지", result.startswith("[거부]"), True)
    check("실패 요약 포함", "2 failed, 25 passed" in result, True)
    check("실패 테스트 이름 노출", "로그아웃 버튼을 클릭하면" in result, True)
    check("플래그 변경 없음", read_feature(root, 1)["passes"], False)
    check("증거 미기록", "verification" in read_feature(root, 1), False)
    check("게이트가 전체 스위트 강제", calls[0]["test_path"], ".")
    check("게이트는 커버리지 요구 안 함", calls[0]["coverage"], False)

    print("\n[2] 테스트 통과 → passes=true 반영 + 증거 기록")
    root = fresh_project()
    stub_jest(0, GREEN)
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    feat = read_feature(root, 1)
    check("완료 메시지", result.startswith("[완료]"), True)
    check("플래그 반영", feat["passes"], True)
    check("증거 기록됨", "verification" in feat, True)
    check("증거 출처", feat["verification"]["verified_by"], "update_features/jest")
    check("증거 요약", "27 passed" in feat["verification"]["summary"], True)
    check("타임스탬프 존재", bool(feat["verification"]["verified_at"]), True)
    check("description 불변", feat["description"], "로그아웃")

    print("\n[3] 테스트 실행 불가 → 거부")
    root = fresh_project()
    stub_jest(None, "[오류] 테스트 타임아웃 (120초)")
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("거부 메시지", result.startswith("[거부]"), True)
    check("원인 전달", "타임아웃" in result, True)
    check("플래그 변경 없음", read_feature(root, 1)["passes"], False)

    print("\n[4] passes=False → 증거 없이 허용, 과거 증거 제거")
    root = fresh_project()
    calls = []
    stub_jest(0, GREEN, calls)
    tools.update_features.invoke({"project_root": str(root), "feature_index": 1, "passes": True})
    check("사전 조건: 증거 있음", "verification" in read_feature(root, 1), True)
    before = len(calls)
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": False}
    )
    check("완료 메시지", result.startswith("[완료]"), True)
    check("플래그 되돌림", read_feature(root, 1)["passes"], False)
    check("과거 증거 제거", "verification" in read_feature(root, 1), False)
    check("jest 재실행 안 함", len(calls), before)

    print("\n[5] 운영자 우회(REQUIRE_TEST_EVIDENCE=false)")
    root = fresh_project()
    calls = []
    stub_jest(1, RED, calls)          # 빨간 스위트여도
    config.REQUIRE_TEST_EVIDENCE = False
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("허용됨", result.startswith("[완료]"), True)
    check("비활성 경고 표시", "증거 게이트가 비활성" in result, True)
    check("jest 호출 안 함", calls, [])
    check("증거 미기록(우회이므로)", "verification" in read_feature(root, 1), False)
    config.REQUIRE_TEST_EVIDENCE = original_flag

    print("\n[6] 잘못된 입력 처리 (회귀)")
    root = fresh_project()
    stub_jest(0, GREEN)
    check(
        "인덱스 범위 초과",
        tools.update_features.invoke(
            {"project_root": str(root), "feature_index": 99, "passes": True}
        ).startswith("[오류]"),
        True,
    )
    check(
        "features.json 없음",
        tools.update_features.invoke(
            {"project_root": str(root / "nope"), "feature_index": 0, "passes": True}
        ).startswith("[오류]"),
        True,
    )

    print("\n[7] _summarize_jest / _failing_tests 단위")
    check("요약 추출", tools._summarize_jest(GREEN), "Test Suites: 5 passed, 5 total | Tests:       27 passed, 27 total")
    check("요약 없음 처리", tools._summarize_jest("no summary here"), "(요약 줄 없음)")
    check("실패 이름 2건", tools._failing_tests(RED).count("●"), 2)

finally:
    tools._run_jest = original_run_jest
    config.REQUIRE_TEST_EVIDENCE = original_flag

print(f"\n{'='*60}")
print(f"TS-006 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

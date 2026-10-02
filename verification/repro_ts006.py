"""
TS-006 검증 스크립트 (TS-008 기준으로 갱신)
───────────────────────────────────────────
update_features(passes=True) 의 증거 게이트 **정책**을 검증한다.

  1) 스위트 빨간불 → 플래그 거부, features.json 무변경
  2) 스위트 녹색 + 기능 태그 통과 → 플래그 반영 + 증거 기록
  3) 테스트 실행 불가 → 거부
  4) passes=False → 증거 없이 허용 + 과거 증거 제거
  5) REQUIRE_TEST_EVIDENCE=false(운영자 우회) → 경고와 함께 허용
  6) 잘못된 입력 → 기존 오류 경로 유지

스텁 지점은 `harness.verify.run_jest_json` 하나다 — jest 실행만 가짜로 두고
태그 판정·단계 커버리지·게이트 정책은 **실제 코드가 돌아간다**.
태그 매칭 자체의 단위 검증은 repro_ts008.py 가 담당한다.
"""
import json
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import config
from harness import tools, verify

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


def fake_results(tests):
    """jest --json 형식의 가짜 결과. tests = [(fullName, status), ...]"""
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "success": failed == 0,
        "numTotalTests": len(tests),
        "numPassedTests": passed,
        "numFailedTests": failed,
        "numTotalTestSuites": 1,
        "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{
            "name": "fake.test.tsx",
            "assertionResults": [
                {"fullName": name, "title": name, "ancestorTitles": [], "status": status}
                for name, status in tests
            ],
        }],
    }


GREEN_TAGGED = fake_results([
    ("F-004.3 F-004.4: 로그아웃 클릭 시 logout 호출 + /login 이동", "passed"),
    ("F-004.5: logout 이 auth_token 을 제거한다", "passed"),
    ("무관한 다른 테스트", "passed"),
])
RED = fake_results([
    ("F-004.3: 로그아웃 클릭 시 logout 호출", "failed"),
    ("무관한 다른 테스트", "passed"),
])


def fresh_project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ts006-"))
    features = [
        {"id": "F-001", "description": "로그인", "passes": True, "steps": ["a"]},
        {"id": "F-004", "description": "로그아웃", "passes": False,
         "steps": ["대시보드 접속", "메뉴 클릭", "로그아웃 클릭", "/login 이동", "토큰 삭제"]},
    ]
    (root / "features.json").write_text(
        json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root


def read_feature(root: Path, index: int) -> dict:
    return json.loads((root / "features.json").read_text(encoding="utf-8"))[index]


def stub_jest(results, diag="", record=None):
    def _stub(project_root):
        if record is not None:
            record.append(project_root)
        return results, diag
    verify.run_jest_json = _stub


# TS-016 의 커버리지 게이트도 스텁한다 — 이 스크립트가 검증하는 것은 게이트 **정책**이고,
# 임시 프로젝트에는 node_modules 가 없어 실제 커버리지 측정이 불가능하다.
# (스텁하지 않으면 측정 실패로 전부 거부되어 정책 검증 자체가 불가능해진다)
verify.coverage_for_feature = lambda *a, **k: (
    {"covered_statements": 12, "files_touched": 1, "sources": ["Thing.tsx (12)"]}, ""
)

original_run_jest_json = verify.run_jest_json
original_flag = config.REQUIRE_TEST_EVIDENCE

try:
    print("\n[1] 스위트 빨간불 → passes=true 거부")
    root = fresh_project()
    calls = []
    stub_jest(RED, record=calls)
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("거부 메시지", result.startswith("[거부]"), True)
    check("회귀 사유 명시", "실패 테스트" in result, True)
    check("플래그 변경 없음", read_feature(root, 1)["passes"], False)
    check("증거 미기록", "verification" in read_feature(root, 1), False)
    check("게이트가 jest 를 직접 실행", len(calls), 1)

    print("\n[2] 스위트 녹색 + 기능 태그 → 반영 + 증거 기록")
    root = fresh_project()
    stub_jest(GREEN_TAGGED)
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    feat = read_feature(root, 1)
    v = feat.get("verification", {})
    check("완료 메시지", result.startswith("[완료]"), True)
    check("플래그 반영", feat["passes"], True)
    check("증거 출처", v.get("verified_by"), "update_features/jest")
    check("판정 수준 기록", v.get("level"), "feature")
    check("증거 테스트 2건 기록", len(v.get("evidence_tests", [])), 2)
    check("무관한 테스트는 증거에서 제외",
          any("무관한" in n for n in v.get("evidence_tests", [])), False)
    check("단계 커버리지 기록", v.get("steps_covered"), [3, 4, 5])
    check("미검증 단계도 기록", v.get("steps_uncovered"), [1, 2])
    check("description 불변", feat["description"], "로그아웃")

    print("\n[3] 스위트는 녹색이지만 이 기능 태그가 없음 → 거부 (TS-008 핵심)")
    root = fresh_project()
    stub_jest(fake_results([("완전히 무관한 테스트", "passed")]))
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("거부됨", result.startswith("[거부]"), True)
    check("사유가 '증거 아님'", "이 기능의 증거가 아닙니다" in result, True)
    check("태그 작성법 안내", 'describe("F-004' in result, True)
    check("플래그 변경 없음", read_feature(root, 1)["passes"], False)

    print("\n[4] 테스트 실행 불가 → 거부")
    root = fresh_project()
    stub_jest(None, "[오류] 테스트 타임아웃 (120초)")
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("거부 메시지", result.startswith("[거부]"), True)
    check("원인 전달", "타임아웃" in result, True)
    check("플래그 변경 없음", read_feature(root, 1)["passes"], False)

    print("\n[5] passes=False → 증거 없이 허용, 과거 증거 제거")
    root = fresh_project()
    calls = []
    stub_jest(GREEN_TAGGED, record=calls)
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

    print("\n[6] 운영자 우회(REQUIRE_TEST_EVIDENCE=false)")
    root = fresh_project()
    calls = []
    stub_jest(RED, record=calls)
    config.REQUIRE_TEST_EVIDENCE = False
    result = tools.update_features.invoke(
        {"project_root": str(root), "feature_index": 1, "passes": True}
    )
    check("허용됨", result.startswith("[완료]"), True)
    check("비활성 경고 표시", "증거 게이트가 비활성" in result, True)
    check("jest 호출 안 함", calls, [])
    check("증거 미기록(우회이므로)", "verification" in read_feature(root, 1), False)
    config.REQUIRE_TEST_EVIDENCE = original_flag

    print("\n[7] 잘못된 입력 처리 (회귀)")
    root = fresh_project()
    stub_jest(GREEN_TAGGED)
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

finally:
    verify.run_jest_json = original_run_jest_json
    config.REQUIRE_TEST_EVIDENCE = original_flag

print(f"\n{'='*60}")
print(f"TS-006 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

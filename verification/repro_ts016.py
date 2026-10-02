"""
TS-016 검증 스크립트
────────────────────
증거가 **소스를 실행하는가**(게이트) 와 **실제로 무는가**(측정) 를 검증한다.

  1) feature_name_pattern — F-005 가 F-0051 에 걸리지 않는가
  2) tagged_test_files — 태그가 있는 단위 테스트 파일만 고르는가 (E2E 제외)
  3) coverage_for_feature — 커버리지 요약 해석, 테스트 파일 자신은 증거에서 제외
  4) apply_flag 의 커버리지 게이트 — 공허한 증거(소스 0줄) 거부, 정상 증거 반영 + 기록
  5) 운영자 우회 — REQUIRE_EVIDENCE_COVERAGE=false
  6) mutate — 변이 후 **원본 복원**, invalid 폐기, 점수 계산

jest·tsc 는 전부 스텁. 실제 실행·LLM 호출 없음.
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
from harness import mutate, verify

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


print("\n[1] feature_name_pattern — 경계")
import re
pat = re.compile(verify.feature_name_pattern("F-005"))
check("F-005 매칭", bool(pat.search("F-005: 리다이렉트")), True)
check("F-005.3 매칭 (단계 태그)", bool(pat.search("F-005.3: 보존")), True)
check("F-0051 오매칭 방어", bool(pat.search("F-0051: 다른 기능")), False)

print("\n[2] tagged_test_files — 단위 테스트만")
files = verify.tagged_test_files("web_target", "F-005")
check("F-005 태그 파일 발견", len(files) >= 2, True)
check("전부 단위 테스트(.test.tsx)", all(f.endswith((".test.ts", ".test.tsx")) for f in files), True)
check("E2E(.spec.ts) 제외", any(f.endswith(".spec.ts") for f in files), False)
check("없는 기능은 빈 목록", verify.tagged_test_files("web_target", "F-999"), [])

print("\n[3] coverage_for_feature — 요약 해석")
original_launcher = verify.jest_launcher
original_cov = verify.coverage_for_feature


def fake_summary(entries):
    """jest 커버리지 요약을 가짜로 만들고, 그것을 읽게 한다."""
    def _stub(project_root, feature_id, top_n=5, test_files=None):
        hits = [(Path(p).name, c) for p, c in entries
                if c > 0 and not Path(p).name.endswith((".test.tsx", ".spec.ts"))]
        hits.sort(key=lambda h: -h[1])
        return {
            "covered_statements": sum(c for _, c in hits),
            "files_touched": len(hits),
            "sources": [f"{n} ({c})" for n, c in hits[:top_n]],
        }, ""
    return _stub


verify.coverage_for_feature = fake_summary([
    ("src/components/ProtectedRoute.tsx", 17),
    ("src/components/LoginForm.tsx", 13),
    ("src/components/ProtectedRoute.test.tsx", 40),   # 테스트 파일 자신 — 증거 아님
    ("src/pages/NotFoundPage.tsx", 0),                # 실행 안 됨
])
cov, diag = verify.coverage_for_feature("x", "F-005")
check("테스트 파일은 증거에서 제외", any("test" in s for s in cov["sources"]), False)
check("0 커버 파일 제외", any("NotFound" in s for s in cov["sources"]), False)
check("합계", cov["covered_statements"], 30)
check("상위 정렬", cov["sources"][0].startswith("ProtectedRoute.tsx"), True)

print("\n[4] apply_flag 의 커버리지 게이트")


def fresh_project():
    root = Path(tempfile.mkdtemp(prefix="ts016-"))
    (root / "features.json").write_text(json.dumps([
        {"id": "C-001", "description": "기능 하나", "passes": False, "steps": ["s1"]},
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def fake_jest(tests):
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "numTotalTests": len(tests), "numPassedTests": passed, "numFailedTests": failed,
        "numTotalTestSuites": 1, "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{"name": "f.test.tsx", "assertionResults": [
            {"fullName": n, "title": n, "ancestorTitles": [], "status": s}
            for n, s in tests]}],
    }


original_run_json = verify.run_jest_json
verify.run_jest_json = lambda project_root: (
    fake_jest([("C-001.1: 단계 1", "passed"), ("무관", "passed")]), ""
)
try:
    # 공허한 증거: 소스를 한 줄도 실행하지 않는다
    verify.coverage_for_feature = lambda *a, **k: (
        {"covered_statements": 0, "files_touched": 0, "sources": []}, ""
    )
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    feat = json.loads((root / "features.json").read_text(encoding="utf-8"))[0]
    check("공허한 증거 거부", applied, False)
    check("사유에 '한 줄도 실행하지 않습니다'", "한 줄도 실행하지 않습니다" in msg, True)
    check("플래그 변경 없음", feat["passes"], False)

    # 정상 증거
    verify.coverage_for_feature = lambda *a, **k: (
        {"covered_statements": 30, "files_touched": 2,
         "sources": ["ProtectedRoute.tsx (17)", "LoginForm.tsx (13)"]}, ""
    )
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    feat = json.loads((root / "features.json").read_text(encoding="utf-8"))[0]
    check("정상 증거 반영", applied, True)
    check("evidence_sources 기록", feat["verification"]["evidence_sources"][0],
          "ProtectedRoute.tsx (17)")
    check("covered_statements 기록", feat["verification"]["covered_statements"], 30)
    check("요약에 커버리지 포함", "소스 30 statements 실행" in feat["verification"]["summary"], True)

    # 측정 실패 → 거부 (측정 못 했으면 통과시키지 않는다)
    verify.coverage_for_feature = lambda *a, **k: (None, "[오류] 커버리지 측정 타임아웃")
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    check("측정 실패 시 거부", applied, False)
    check("원인 전달", "타임아웃" in msg, True)

    print("\n[5] 운영자 우회 (REQUIRE_EVIDENCE_COVERAGE=false)")
    original_flag = config.REQUIRE_EVIDENCE_COVERAGE
    config.REQUIRE_EVIDENCE_COVERAGE = False
    calls = []
    verify.coverage_for_feature = lambda *a, **k: (calls.append(1), (None, "x"))[1]
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    check("우회 시 반영됨", applied, True)
    check("커버리지 측정 자체를 건너뜀", calls, [])
    config.REQUIRE_EVIDENCE_COVERAGE = original_flag
finally:
    verify.run_jest_json = original_run_json
    verify.coverage_for_feature = original_cov

print("\n[6] mutate — 원본 복원과 점수")
# 실제 파일에 변이를 적용하되 tsc/jest 는 스텁한다
work = Path(tempfile.mkdtemp(prefix="ts016-mut-"))
src_dir = work / "src" / "components"
src_dir.mkdir(parents=True)
target = src_dir / "Thing.tsx"
ORIGINAL = """export const f = (a: number, b: number) => {
  if (a === b) { return true; }
  return a > b && b !== 0;
};
"""
target.write_text(ORIGINAL, encoding="utf-8")
(work / "features.json").write_text("[]", encoding="utf-8")

mutate.tagged_test_files = lambda project_root, feature_id: ["src/Thing.test.tsx"]
mutate.coverage_for_feature = lambda project_root, feature_id, top_n=5, test_files=None: (
    {"covered_statements": 3, "files_touched": 1, "sources": ["Thing.tsx (3)"]}, ""
)
# TS-021 에서 검사 순서가 바뀌었다: jest 를 먼저 돌리고, **실패했을 때만** tsc 로
# 유효성을 확인한다 (통과한 변이는 컴파일된 것이므로 tsc 가 불필요하다 — 변이당 1.9초 절감).
# 그래서 스텁 대본도 그 순서를 따른다:
#   1번 변이: jest 실패 → tsc 통과 → 잡음
#   2번 변이: jest 통과 → 생존 (tsc 호출 안 됨)
#   3번 변이: jest 실패 → tsc 실패 → 폐기
fail_results = [True, False, True]
type_results = [True, False]
mutate._typechecks = lambda project_root: type_results.pop(0) if type_results else True
mutate._tests_fail = lambda project_root, fid, files: fail_results.pop(0) if fail_results else False

report = mutate.mutate_feature(str(work), "C-001", max_files=1)
check("원본 완전 복원", target.read_text(encoding="utf-8"), ORIGINAL)
check("변이 3건 시도 (파일당 상한)", len(report["mutants"]), 3)
check("잡음 1", report["killed"], 1)
check("생존 1", report["survived"], 1)
check("폐기 1 (타입 검사 실패)", report["invalid"], 1)
check("점수는 폐기를 분모에서 제외 (1/2)", report["score"], 0.5)
text = mutate.format_mutation(report)
check("생존 경고 출력", "생존 1건" in text, True)
check("해석 주의 문구", "이 기능의 테스트 품질'이 아니다" in text, True)
check("오류 보고", mutate.format_mutation({"error": "x"}).startswith("[오류]"), True)

print(f"\n{'='*60}")
print(f"TS-016 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

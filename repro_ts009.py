"""
TS-009 검증 스크립트
────────────────────
하네스 자체를 측정하는 계층을 검증한다 (harness/metrics.py + night_shift 의 [END] 기록).

  1) 판별력 측정 — 수준별 통과 건수와 A/B 수치가 정확한가
  2) 플래그 감사 — 증거 없는 통과 / 증거 있는데 미완성 표시를 잡아내는가
  3) 실행 로그 파싱 — [END] 를 사람용 마커보다 우선하고, 네 가지 종료 상태를 구분하는가
  4) 과거 블록 호환 — [END] 없는 블록은 unknown 으로 남고 소요 시간은 추정으로 채우는가
  5) 출력 포맷 — 핵심 수치가 실제로 표에 들어가는가

jest 는 가짜 JSON, 로그는 임시 파일. LLM·네트워크 접근 없음.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from harness import metrics, verify

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
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "numTotalTests": len(tests),
        "numPassedTests": passed,
        "numFailedTests": failed,
        "numTotalTestSuites": 1,
        "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{
            "name": "fake.test.tsx",
            "assertionResults": [
                {"fullName": n, "title": n, "ancestorTitles": [], "status": s}
                for n, s in tests
            ],
        }],
    }


# A-001: 기능 태그 + 전 단계 태그 (step 수준까지 통과)
# A-002: 기능 태그만 (feature 통과, step 거부)
# A-003: 태그 없음 — 그런데 passes=true 로 기록됨 (증거 없는 통과)
# A-004: 태그 있는데 passes=false (증거 있는데 미완성 표시)
FEATURES = [
    {"id": "A-001", "description": "로그인", "passes": True, "steps": ["s1", "s2"]},
    {"id": "A-002", "description": "로그아웃", "passes": True, "steps": ["s1", "s2"]},
    {"id": "A-003", "description": "순위표", "passes": True, "steps": ["s1"]},
    {"id": "A-004", "description": "차트", "passes": False, "steps": ["s1"]},
]
RESULTS = fake_results([
    ("A-001.1: 단계 1", "passed"),
    ("A-001.2: 단계 2", "passed"),
    ("A-002: 로그아웃 동작", "passed"),
    ("A-004.1: 차트 표시", "passed"),
    ("무관한 테스트", "passed"),
])

original_run_jest_json = verify.run_jest_json
verify.run_jest_json = lambda project_root: (RESULTS, "")

try:
    print("\n[1] 판별력 측정 — 수준별 통과 건수")
    report = metrics.discrimination_report("x", features=FEATURES)
    lv = report["levels"]
    check("suite: 전부 통과 (판별력 0)", lv["suite"]["accepted"], 4)
    check("suite 통과율 100%", lv["suite"]["accept_rate"], 1.0)
    check("feature: 태그 있는 3건만", sorted(lv["feature"]["accepted_ids"]),
          ["A-001", "A-002", "A-004"])
    check("step: 전 단계 태그된 2건만", sorted(lv["step"]["accepted_ids"]),
          ["A-001", "A-004"])
    check("거부 사유 분류", lv["feature"]["reject_reasons"], {"기능 태그 없음": 1})

    print("\n[2] A/B 수치 (baseline=suite vs treatment=feature)")
    ab = report["ab_suite_vs_feature"]
    check("baseline 통과", ab["baseline_accepted"], 4)
    check("treatment 통과", ab["treatment_accepted"], 3)
    check("걸러낸 건수", ab["filtered_out"], 1)
    check("판별력 = 1 - 3/4", ab["discrimination"], 0.25)

    print("\n[3] 플래그 감사")
    check("증거 없는 통과 적발", report["unsupported_flags"], ["A-003"])
    check("증거 있는데 미완성 표시 적발", report["unclaimed_passes"], ["A-004"])
    check("플래그 목록", report["flagged_passes"], ["A-001", "A-002", "A-003"])

    print("\n[4] 회귀가 있으면 모든 수준이 0건")
    red = fake_results([("A-001.1: 단계 1", "passed"), ("다른 테스트", "failed")])
    verify.run_jest_json = lambda project_root: (red, "")
    report_red = metrics.discrimination_report("x", features=FEATURES)
    check("suite 통과 0건", report_red["levels"]["suite"]["accepted"], 0)
    check("feature 통과 0건", report_red["levels"]["feature"]["accepted"], 0)
    check("사유가 회귀", report_red["levels"]["suite"]["reject_reasons"],
          {"회귀(스위트 빨간불)": 4})

    print("\n[5] jest 실행 불가 시")
    verify.run_jest_json = lambda project_root: (None, "[오류] jest 없음")
    broken = metrics.discrimination_report("x", features=FEATURES)
    check("error 반환", "error" in broken, True)
    check("빈 levels", broken["levels"], {})
    check("포맷 함수가 오류를 표시", metrics.format_discrimination(broken).startswith("[오류]"), True)

finally:
    verify.run_jest_json = original_run_jest_json


print("\n[6] 실행 로그 파싱 — [END] 네 가지 상태")
log = Path(tempfile.mkdtemp(prefix="ts009-")) / "run.log"
log.write_text("""
============================================================
TASK START: 기능 하나
SESSION: feature-F-004
TIME: 2026-10-01 10:00:00
============================================================
[SUCCESS] Task completed

[END] exit=0 outcome=success elapsed_sec=12.5

============================================================
TASK START: 기능 둘
SESSION: feature-F-005
TIME: 2026-10-01 10:05:00
============================================================
[ERROR] Task failed with exit code 3

[END] exit=3 outcome=infra elapsed_sec=7.0

============================================================
TASK START: 기능 셋
SESSION: feature-F-005
TIME: 2026-10-01 10:10:00
============================================================
[END] exit=-1 outcome=timeout elapsed_sec=1800.0

============================================================
TASK START: 기능 넷
SESSION: feature-F-006
TIME: 2026-10-01 10:40:00
============================================================
[END] exit=None outcome=aborted(KeyboardInterrupt) elapsed_sec=3.2
""", encoding="utf-8")

stats = metrics.run_log_stats(str(log))
check("총 시도 4회", stats["total_runs"], 4)
check("결과 분포", stats["outcomes"],
      {"success": 1, "infra": 1, "timeout": 1, "aborted(KeyboardInterrupt)": 1})
check("unknown 0건", stats["outcomes"].get("unknown", 0), 0)
check("세션별 시도 집계", stats["attempts_per_session"]["feature-F-005"], 2)
check("최대 시도", stats["max_attempts"], 2)
check("정확한 소요 시간 사용 (추정 아님)", stats["runs"][0].duration_sec, 12.5)
check("타임아웃 소요 시간", stats["runs"][2].duration_sec, 1800.0)
check("[END] 가 사람용 마커를 덮어씀 (exit=3 → infra)", stats["runs"][1].outcome, "infra")

print("\n[7] 과거 블록 호환 — [END] 없는 로그")
legacy = Path(tempfile.mkdtemp(prefix="ts009-legacy-")) / "run.log"
legacy.write_text("""
============================================================
TASK START: 옛 기능
SESSION: feature-F-004
TIME: 2026-04-14 21:47:37
============================================================
Traceback (most recent call last):
  RuntimeError: 무언가 터짐

============================================================
TASK START: 옛 기능 재시도
SESSION: feature-F-004
TIME: 2026-04-14 21:47:44
============================================================
[ERROR] Task failed with exit code 1
""", encoding="utf-8")
legacy_stats = metrics.run_log_stats(str(legacy))
check("마커 없는 블록은 unknown", legacy_stats["outcomes"].get("unknown"), 1)
check("사람용 마커는 여전히 인식", legacy_stats["outcomes"].get("failed"), 1)
check("소요 시간은 시작 시각 차이로 추정", legacy_stats["runs"][0].duration_sec, 7.0)

print("\n[8] 로그 파일 없음")
missing = metrics.run_log_stats(str(log.parent / "nope.log"))
check("error 반환", "error" in missing, True)
check("포맷 함수가 오류 표시", metrics.format_run_log(missing).startswith("[오류]"), True)

print("\n[9] 출력 포맷에 핵심 수치가 들어가는가")
verify.run_jest_json = lambda project_root: (RESULTS, "")
try:
    text = metrics.format_discrimination(metrics.discrimination_report("x", features=FEATURES))
finally:
    verify.run_jest_json = original_run_jest_json
check("판별력 표기", "판별력" in text, True)
check("A/B 블록 포함", "baseline" in text, True)
check("증거 없는 통과 노출", "A-003" in text, True)
log_text = metrics.format_run_log(stats)
check("결과 분포 표기", "success" in log_text, True)
check("즉시 실패 경고", "즉시 실패한 런" in log_text, True)

print(f"\n{'='*60}")
print(f"TS-009 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

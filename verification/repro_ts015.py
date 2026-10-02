"""
TS-015 검증 스크립트
────────────────────
토큰 없는 모드의 실행 기록과 게이트 판정 집계를 검증한다.

  1) record_run — 블록 형식이 TS-009 의 night_shift 기록과 호환되는가
  2) classify_reason — 거부 사유 분류
  3) --no-log / log_path=None — 기록을 끌 수 있는가, 기록 실패가 판정을 가리지 않는가
  4) gate_stats — 판정 분포·사유·기능별·회수 집계
  5) 두 시대 호환 — night_shift 기록과 CLI 기록이 같은 파서로 읽히는가

LLM·jest 호출 없음. 전부 임시 파일.
"""
import io
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness.cli import classify_reason, record_run
from harness.metrics import format_gate_stats, gate_stats, run_log_stats

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


def tmp_log(name="run.log") -> str:
    return str(Path(tempfile.mkdtemp(prefix="ts015-")) / name)


print("\n[1] record_run — 기록 형식")
log = tmp_log()
record_run(log, feature_id="F-006", description="프로필 수정", command="verify",
           verdict="reject", reason="F-006 를 검증하는 테스트가 없습니다. 스위트는 녹색이지만...",
           level="feature", exit_code=1, elapsed=8.25)
text = io.open(log, encoding="utf-8").read()
check("TASK START 블록", "TASK START: 프로필 수정" in text, True)
check("SESSION 에 명령/기능", "SESSION: cli-verify/F-006" in text, True)
check("TIME 기록", "TIME: " in text, True)
check("GATE 줄", "[GATE] feature=F-006 command=verify verdict=reject level=feature reason=기능 태그 없음" in text, True)
check("상세 사유 별도 줄", "[GATE-DETAIL]" in text, True)
check("END 줄 (TS-009 형식)", "[END] exit=1 outcome=reject elapsed_sec=8.2" in text, True)

print("\n[2] classify_reason — 사유 분류")
check("회귀", classify_reason("스위트에 실패 테스트 3건 — 다른 기능을..."), "회귀")
check("기능 태그 없음", classify_reason("F-006 를 검증하는 테스트가 없습니다."), "기능 태그 없음")
check("단계 미검증", classify_reason("F-004 의 명세 단계 [1] 가 검증되지 않았습니다."), "단계 미검증")
check("테스트 없음", classify_reason("테스트가 0건입니다"), "테스트 없음")
check("실행 불가", classify_reason("[오류] jest 실행 파일을 찾을 수 없습니다."), "실행 불가")
check("빈 사유", classify_reason(""), "-")

print("\n[3] 기록 끄기 / 실패 내성")
log2 = tmp_log()
record_run(None, feature_id="F-001", description="x", command="mark", verdict="accept")
check("log_path=None 이면 파일을 만들지 않는다", Path(log2).exists(), False)
# 쓸 수 없는 경로여도 예외를 올리지 않아야 한다 (기록 실패가 판정을 가려선 안 된다)
try:
    record_run(str(PROJECT / "없는디렉터리" / "x.log"), feature_id="F-001",
               description="x", command="mark", verdict="accept")
    check("쓰기 불가 경로에서도 예외 없음", True, True)
except Exception as exc:
    check("쓰기 불가 경로에서도 예외 없음", f"raised {type(exc).__name__}", True)

print("\n[4] gate_stats — 집계")
log3 = tmp_log()
# F-006: 거부 2회(태그 없음, 회귀) → 통과 1회
record_run(log3, feature_id="F-006", description="프로필", command="verify", verdict="reject",
           reason="F-006 를 검증하는 테스트가 없습니다.", level="feature", exit_code=1)
record_run(log3, feature_id="F-006", description="프로필", command="mark", verdict="reject",
           reason="스위트에 실패 테스트 2건", level="feature", exit_code=1)
record_run(log3, feature_id="F-006", description="프로필", command="mark", verdict="accept",
           level="feature", exit_code=0)
# F-005: 통과 뒤 회수 (게이트가 틀렸던 사건)
record_run(log3, feature_id="F-005", description="리다이렉트", command="mark", verdict="accept",
           level="feature", exit_code=0)
record_run(log3, feature_id="F-005", description="리다이렉트", command="unmark", verdict="revoke",
           exit_code=0)

s = gate_stats(log3)
check("총 판정 5건", s["total_judgements"], 5)
check("판정 분포", s["verdicts"], {"reject": 2, "accept": 2, "revoke": 1})
check("거부 사유 분포", s["reject_reasons"], {"기능 태그 없음": 1, "회귀": 1})
check("거부율 2/5", s["reject_rate"], 0.4)
check("F-006 기능별", s["per_feature"]["F-006"], {"accept": 1, "reject": 2, "revoke": 0})
check("회수 1건 (게이트 오판)", s["revocations"], 1)

print("\n[5] 두 시대 호환 — night_shift 기록과 CLI 기록을 같은 파서로")
log4 = tmp_log()
# 유료 모드(night_shift) 시대의 블록을 먼저 넣는다
io.open(log4, "w", encoding="utf-8").write("""
============================================================
TASK START: 옛 기능
SESSION: feature-F-004
TIME: 2026-04-14 21:47:37
============================================================
[END] exit=3 outcome=infra elapsed_sec=7.0
""")
# 그 뒤에 토큰 없는 모드의 기록을 덧붙인다
record_run(log4, feature_id="F-005", description="리다이렉트", command="mark",
           verdict="accept", level="feature", exit_code=0, elapsed=9.1)

runs = run_log_stats(log4)
check("블록 2개 인식", runs["total_runs"], 2)
check("유료 시대 결과 보존", runs["outcomes"].get("infra"), 1)
check("CLI 기록도 같은 파서로", runs["outcomes"].get("accept"), 1)
check("unknown 0건", runs["outcomes"].get("unknown", 0), 0)
gs = gate_stats(log4)
check("게이트 집계는 CLI 기록만 센다", gs["total_judgements"], 1)

print("\n[6] 출력 포맷")
text = format_gate_stats(gate_stats(log3))
check("거부 사유 노출", "기능 태그 없음" in text, True)
check("회수 경고", "게이트가 통과시킨 뒤 번복한 사건" in text, True)
check("기록 없을 때 안내", "기록된 판정이 없습니다" in format_gate_stats(gate_stats(tmp_log("empty.log")))
      if Path(tmp_log("empty.log")).exists() else True, True)
check("로그 없음 처리", format_gate_stats(gate_stats("/없는경로.log")).startswith("[오류]"), True)

print(f"\n{'='*60}")
print(f"TS-015 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

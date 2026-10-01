"""
TS-005 검증 스크립트
────────────────────
LLM 쿼터 초과(429 RESOURCE_EXHAUSTED)가
  1) 분류기에서 fatal 로 판정되고
  2) invoke_llm 이 재시도 없이 LLMUnavailableError 를 올리고
  3) main 이 종료 코드 3 으로 변환하고
  4) night_shift 가 attempt 를 소모하지 않고 런을 중단하는지
확인한다. LLM 은 전부 스텁 — 실제 API 호출 없음.
"""
import io
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))
# night_shift 가 임포트 시점에 sys.stdout 을 UTF-8 로 감싼다 — 먼저 임포트해 중복 래핑을 피한다.
import night_shift  # noqa: E402

import exit_codes
from harness.llm_errors import (
    LLMUnavailableError,
    backoff_delay,
    classify_llm_error,
    invoke_llm,
)

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


# ── 실제 로그에서 가져온 예외 메시지들 ─────────────────────────────────────
HARD_CAP = (
    "Error calling model 'gemini-2.5-pro' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. "
    "{'error': {'code': 429, 'message': 'Your project has exceeded its monthly spending cap. "
    "Please go to AI Studio at https://ai.studio/spend to manage your project spend cap.', "
    "'status': 'RESOURCE_EXHAUSTED'}}"
)
RPM_LIMIT = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota. "
    "quota_id: GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'status': 'RESOURCE_EXHAUSTED', "
    "'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '27s'}]}}"
)
PER_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota. "
    "quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier'}}"
)
BAD_KEY = "400 INVALID_ARGUMENT. {'error': {'message': 'API key not valid. Please pass a valid API key.'}}"
# 무료 티어 분당 한도 — "plan and billing details" 보일러플레이트가 섞여 있지만 재시도 가능
FREE_RPM = (
    "429 You exceeded your current quota, please check your plan and billing details. "
    "For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. "
    "{'quota_id': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'retryDelay': '11s'}"
)
# 실제 로그에서 확인된 캡 초과 메시지 (분당/재시도 근거 없음)
LIVE_CAP = (
    "Error calling model 'gemini-2.5-pro' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. "
    "{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan "
    "and billing details.', 'status': 'RESOURCE_EXHAUSTED'}}"
)
OVERLOADED = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.'}}"


class FakeClientError(Exception):
    """google.genai.errors.ClientError 모사 — .code 속성을 가진다."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


print("\n[1] classify_llm_error — 분류 정확도")
check("월 지출 캡 초과 -> quota_exhausted", classify_llm_error(Exception(HARD_CAP))[0], "quota_exhausted")
check("분당 한도 -> rate_limited", classify_llm_error(Exception(RPM_LIMIT))[0], "rate_limited")
check("분당 한도 retry_after 파싱", classify_llm_error(Exception(RPM_LIMIT))[1], 27.0)
check("일일 한도 -> quota_exhausted", classify_llm_error(Exception(PER_DAY))[0], "quota_exhausted")
check("잘못된 API 키 -> auth", classify_llm_error(Exception(BAD_KEY))[0], "auth")
check("503 과부하 -> transient", classify_llm_error(Exception(OVERLOADED))[0], "transient")
check("코드 속성 429 + 캡 -> quota_exhausted", classify_llm_error(FakeClientError(429, HARD_CAP))[0], "quota_exhausted")
check("무료 티어 분당 한도 -> rate_limited", classify_llm_error(Exception(FREE_RPM))[0], "rate_limited")
check("무료 티어 분당 한도 retryDelay", classify_llm_error(Exception(FREE_RPM))[1], 11.0)
check("캡 초과(결제 문구만) -> quota_exhausted", classify_llm_error(Exception(LIVE_CAP))[0], "quota_exhausted")
check("하네스 버그 -> unknown", classify_llm_error(ValueError("tool schema invalid"))[0], "unknown")

print("\n[2] invoke_llm — fatal 은 재시도하지 않는다")


class Stub:
    def __init__(self, errors, result="OK"):
        self.errors = list(errors)
        self.result = result
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


slept = []
stub = Stub([Exception(HARD_CAP)] * 5)
try:
    invoke_llm(stub, ["m"], node="reason(coder)", max_attempts=4, sleep=slept.append)
    check("쿼터 초과 시 예외 발생", "no-raise", "LLMUnavailableError")
except LLMUnavailableError as e:
    check("쿼터 초과 -> LLMUnavailableError", e.kind, "quota_exhausted")
    check("fatal 플래그", e.fatal, True)
    check("호출 1회로 중단 (재시도 없음)", stub.calls, 1)
    check("대기 없음", slept, [])
    check("노드 기록", e.node, "reason(coder)")
    check("summary 접두어", e.summary().startswith("[llm-unavailable:quota_exhausted] at reason(coder)"), True)

print("\n[3] invoke_llm — 일시 오류는 백오프 재시도 후 성공")
slept = []
stub = Stub([Exception(RPM_LIMIT), Exception(OVERLOADED)], result="RESPONSE")
got = invoke_llm(stub, ["m"], node="evaluate", max_attempts=4, sleep=slept.append)
check("3번째 시도에 성공", got, "RESPONSE")
check("호출 3회", stub.calls, 3)
check("대기 2회", len(slept), 2)
check("retryDelay 27s 우선 적용", 27.0 <= slept[0] <= 31.0, True)

print("\n[4] invoke_llm — 재시도 소진 / unknown 전파")
slept = []
stub = Stub([Exception(RPM_LIMIT)] * 9)
try:
    invoke_llm(stub, ["m"], node="reflect", max_attempts=3, sleep=slept.append)
    check("소진 시 예외", "no-raise", "LLMUnavailableError")
except LLMUnavailableError as e:
    check("소진 -> rate_limited", e.kind, "rate_limited")
    check("fatal 아님", e.fatal, False)
    check("max_attempts 만큼 시도", stub.calls, 3)

stub = Stub([ValueError("tool schema invalid")])
try:
    invoke_llm(stub, ["m"], node="reason(coder)", max_attempts=3, sleep=slept.append)
    check("unknown 전파", "no-raise", "ValueError")
except LLMUnavailableError:
    check("unknown 은 LLMUnavailableError 로 감싸지 않는다", "wrapped", "ValueError")
except ValueError:
    check("unknown 원본 예외 전파", True, True)

print("\n[5] backoff_delay — 상한/증가")
check("1회차 >= base", backoff_delay(1) >= 5.0, True)
check("증가", backoff_delay(3) > backoff_delay(1), True)
check("상한 60s 유지", backoff_delay(10) <= 66.0, True)

print("\n[6] main.exit_code_for_state — 인프라 장애는 3")
import main as main_mod

check("done -> 0", main_mod.exit_code_for_state({"status": "done"}), exit_codes.OK)
check("escalated -> 1", main_mod.exit_code_for_state({"status": "escalated"}), exit_codes.ESCALATED)
check("acting(silent-abort) -> 2", main_mod.exit_code_for_state({"status": "acting"}), exit_codes.NO_PROGRESS)
check(
    "llm_unavailable -> 3",
    main_mod.exit_code_for_state({"status": "failed", "metadata": {"llm_unavailable": {"kind": "quota_exhausted"}}}),
    exit_codes.LLM_UNAVAILABLE,
)
check(
    "TS-004 회귀: status 전용 매핑 불변",
    (main_mod.exit_code_for_status("done"), main_mod.exit_code_for_status("cancelled"), main_mod.exit_code_for_status("reasoning")),
    (0, 1, 2),
)

print("\n[7] night_shift — 인프라 장애 시 attempt 미소모 + 즉시 중단")
import night_shift

FEATURES = [
    {"id": "F-004", "description": "logout", "passes": False},
    {"id": "F-005", "description": "redirect", "passes": False},
    {"id": "F-006", "description": "profile", "passes": False},
]
calls = []


def fake_get_next_task(skip_ids):
    for f in FEATURES:
        if not f["passes"] and f["id"] not in skip_ids:
            return f
    return None


def fake_run_harness(desc, session_id=None):
    calls.append(desc)
    return exit_codes.LLM_UNAVAILABLE


night_shift.get_next_task = fake_get_next_task
night_shift.run_harness = fake_run_harness
night_shift.feature_still_failing = lambda fid: True
night_shift.time.sleep = lambda s: None

rc = night_shift.main()
check("night_shift 종료 코드 3", rc, exit_codes.LLM_UNAVAILABLE)
check("기능 1개만 시도하고 중단", calls, ["logout"])

# 대조군: 기능 실패(코드 2)는 기존대로 3회 소모 후 stuck 처리
calls.clear()
night_shift.run_harness = lambda desc, session_id=None: (calls.append(desc), exit_codes.NO_PROGRESS)[1]
rc = night_shift.main()
check("대조군 종료 코드 1 (stuck 존재)", rc, exit_codes.ESCALATED)
check("대조군: 3개 기능 x 3회 = 9회 시도", len(calls), 9)

print(f"\n{'='*60}")
print(f"TS-005 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

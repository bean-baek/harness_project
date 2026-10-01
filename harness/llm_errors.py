"""
harness/llm_errors.py
─────────────────────
LLM 공급자(Gemini) 오류 분류 + 백오프 재시도 래퍼

배경 (TS-005):
  Gemini 호출이 `429 RESOURCE_EXHAUSTED`(월 지출 한도 초과)로 실패하면 예외가
  그래프 밖으로 그대로 전파되어 main.py 가 트레이스백과 함께 죽었다.
  night_shift.py 는 이 종료를 '기능 구현 실패'로 오인해 attempt 를 소모하고
  기능을 stuck 으로 마킹했다 — 원인이 기능과 전혀 무관한 인프라 장애인데도.

설계:
  classify_llm_error()  예외 → (kind, retry_after)
      quota_exhausted / auth      → 재시도 무의미 (fatal)
      rate_limited / transient    → 지수 백오프 후 재시도
      unknown                     → 하네스 버그일 수 있으므로 숨기지 않고 원본 전파

  invoke_llm()  모든 노드의 LLM 호출 단일 진입점.
      fatal 이거나 재시도를 소진하면 LLMUnavailableError 를 올리고,
      main.py 가 이를 전용 종료 코드(exit_codes.LLM_UNAVAILABLE)로 변환한다.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any, Callable, Literal

import config

LLMErrorKind = Literal["quota_exhausted", "rate_limited", "auth", "transient", "unknown"]

#: 재시도해도 의미가 없는 분류 — 즉시 런을 중단해야 한다.
FATAL_KINDS: frozenset[str] = frozenset({"quota_exhausted", "auth"})


# ── 분류 패턴 ────────────────────────────────────────────────────────────────

# 하드 한도(강한 신호): 지출 캡 또는 '일(日)' 단위 쿼터 — 몇 초 뒤 재시도로 열리지 않는다.
# 주의: "...FreeTier" 자체는 하드 신호가 아니다 (분당 한도도 FreeTier 라벨을 쓴다).
_HARD_QUOTA_PATTERNS = (
    "spending cap",
    "spend cap",
    "monthly spending",
    "exceeded its monthly",
    "perday",
    "per day",
    "per-day",
    "daily limit",
)

# 하드 한도(약한 신호): 분당 한도 메시지에도 "plan and billing details" 보일러플레이트가
# 섞여 나오므로, 분당/재시도 근거가 전혀 없을 때만 하드로 간주한다.
_WEAK_HARD_PATTERNS = (
    "billing",
    "upgrade your plan",
)

# 분당 한도 — 백오프 후 재시도하면 창이 열린다.
_PER_MINUTE_PATTERNS = (
    "perminute",
    "per minute",
    "per-minute",
    "requests per min",
    "rate-limits",
    "rate_limits",
)

_AUTH_PATTERNS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "permission_denied",
    "unauthenticated",
    "credential",
)

_RATE_LIMIT_PATTERNS = (
    "resource_exhausted",
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
)

_TRANSIENT_PATTERNS = (
    "unavailable",
    "deadline exceeded",
    "timed out",
    "timeout",
    "internal error",
    "internal server",
    "overloaded",
    "connection reset",
    "connection aborted",
    "temporarily",
)

_STATUS_RE = re.compile(r"\b(400|401|403|404|408|429|499|500|502|503|504)\b")

# retryDelay: 27s  /  retry-after: 30  /  retry in 27s
_RETRY_AFTER_RES = (
    re.compile(r"retry[-_ ]?delay[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)\s*s?", re.I),
    re.compile(r"retry[-_ ]?after[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)", re.I),
    re.compile(r"retry\s+in\s+(\d+(?:\.\d+)?)\s*s", re.I),
)


class LLMUnavailableError(RuntimeError):
    """LLM 공급자를 사용할 수 없음 — 기능 실패가 아닌 인프라 장애.

    Attributes:
        kind:        분류 (quota_exhausted / auth / rate_limited / transient)
        node:        호출이 발생한 그래프 노드 이름
        attempts:    소모한 시도 횟수
        retry_after: 공급자가 알려준 대기 시간(초). 없으면 None
        original:    원본 예외
    """

    def __init__(
        self,
        kind: LLMErrorKind,
        message: str,
        *,
        node: str = "",
        attempts: int = 0,
        retry_after: float | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.node = node
        self.attempts = attempts
        self.retry_after = retry_after
        self.original = original

    @property
    def fatal(self) -> bool:
        """재시도가 무의미한 장애인지 여부."""
        return self.kind in FATAL_KINDS

    def advice(self) -> str:
        """운영자가 취해야 할 조치."""
        if self.kind == "quota_exhausted":
            return (
                "Gemini 프로젝트의 지출/일일 한도를 초과했습니다. "
                "https://ai.studio/spend 에서 한도를 올리거나 다음 결제 주기까지 대기하십시오. "
                "저비용 모델로 계속하려면 HARNESS_LLM_MODEL=gemini-2.5-flash 로 재실행하십시오."
            )
        if self.kind == "auth":
            return (
                "GOOGLE_API_KEY 가 유효하지 않거나 권한이 없습니다. "
                ".env 의 키를 확인하고 `python repro_bug.py` 로 단독 검증하십시오."
            )
        if self.kind == "rate_limited":
            return (
                f"분당 요청 한도에 반복 도달했습니다 ({self.attempts}회 백오프 소진). "
                "HARNESS_LLM_MAX_ATTEMPTS / HARNESS_LLM_BACKOFF_MAX 를 늘리거나 "
                "잠시 후 재실행하십시오."
            )
        return (
            "LLM 공급자가 일시적으로 응답하지 않습니다 "
            f"({self.attempts}회 재시도 소진). 네트워크를 확인하고 재실행하십시오."
        )

    def summary(self) -> str:
        """한 줄 요약 — error_log / metadata 기록용."""
        where = f" at {self.node}" if self.node else ""
        first_line = str(self).splitlines()[0] if str(self) else self.kind
        return f"[llm-unavailable:{self.kind}]{where} {first_line[:300]}"


# ── 분류기 ───────────────────────────────────────────────────────────────────

def _status_code(exc: BaseException) -> int | None:
    """예외에서 HTTP 상태 코드를 최대한 끌어낸다."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def _parse_retry_after(text: str) -> float | None:
    """공급자가 제시한 재시도 대기 시간(초)을 추출한다."""
    for pattern in _RETRY_AFTER_RES:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def classify_llm_error(exc: BaseException) -> tuple[LLMErrorKind, float | None]:
    """LLM 호출 예외를 (kind, retry_after) 로 분류한다.

    langchain_google_genai 는 원본 `google.genai.errors.ClientError` 를
    `ChatGoogleGenerativeAIError` 로 감싸므로 타입이 아닌 **코드/메시지**로 판정한다.
    """
    raw = f"{type(exc).__name__}: {exc}"
    text = raw.lower()
    code = _status_code(exc)

    if code in (401, 403) or any(p in text for p in _AUTH_PATTERNS):
        return "auth", None

    if code == 429 or any(p in text for p in _RATE_LIMIT_PATTERNS):
        retry_after = _parse_retry_after(raw)
        # 1) 지출 캡 / 일일 쿼터 — 명확한 하드 한도
        if any(p in text for p in _HARD_QUOTA_PATTERNS):
            return "quota_exhausted", None
        # 2) 분당 한도 또는 공급자가 재시도 시점을 제시 — 백오프하면 열린다
        if retry_after is not None or any(p in text for p in _PER_MINUTE_PATTERNS):
            return "rate_limited", retry_after
        # 3) 분당/재시도 근거 없이 결제 문구만 있으면 하드로 본다
        if any(p in text for p in _WEAK_HARD_PATTERNS):
            return "quota_exhausted", None
        return "rate_limited", None

    if code is not None and 500 <= code < 600:
        return "transient", _parse_retry_after(raw)

    if any(p in text for p in _TRANSIENT_PATTERNS):
        return "transient", _parse_retry_after(raw)

    return "unknown", None


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """지수 백오프 대기 시간(초). 공급자가 준 retry_after 가 있으면 그것을 우선한다."""
    base = float(getattr(config, "LLM_BACKOFF_BASE_SEC", 5.0))
    cap = float(getattr(config, "LLM_BACKOFF_MAX_SEC", 60.0))
    if retry_after is not None:
        delay = min(retry_after + 1.0, cap)
    else:
        delay = min(base * (2 ** max(attempt - 1, 0)), cap)
    # 지터 — 여러 호출이 동시에 재진입해 같은 한도를 다시 때리는 것을 방지
    return round(delay + random.uniform(0, min(delay * 0.1, 3.0)), 2)


# ── 호출 래퍼 ────────────────────────────────────────────────────────────────

def invoke_llm(
    llm: Any,
    messages: Any,
    *,
    node: str = "",
    max_attempts: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """LLM 을 호출하고, 일시적 공급자 오류는 백오프 재시도한다.

    Args:
        llm:          `.invoke()` 를 가진 LLM (bind_tools 결과 포함)
        messages:     전달할 메시지 리스트
        node:         호출 주체 노드 이름 (오류 보고용)
        max_attempts: 최대 시도 횟수 (기본: config.LLM_MAX_ATTEMPTS)
        sleep:        대기 함수 (테스트에서 주입)

    Returns:
        LLM 응답 메시지

    Raises:
        LLMUnavailableError: 쿼터/인증 등 재시도 무의미, 또는 백오프 소진
        원본 예외:           분류 불가(unknown) — 하네스 버그를 숨기지 않는다
    """
    attempts = int(max_attempts or getattr(config, "LLM_MAX_ATTEMPTS", 4))
    attempts = max(attempts, 1)

    for attempt in range(1, attempts + 1):
        try:
            return llm.invoke(messages)
        except Exception as exc:                      # noqa: BLE001 — 분류 후 재전파
            kind, retry_after = classify_llm_error(exc)

            if kind == "unknown":
                raise

            err = LLMUnavailableError(
                kind,
                str(exc),
                node=node,
                attempts=attempt,
                retry_after=retry_after,
                original=exc,
            )

            if err.fatal:
                print(f"[llm-{kind}] {node or 'llm'} — 재시도 무의미, 즉시 중단")
                raise err from exc

            if attempt >= attempts:
                raise err from exc

            delay = backoff_delay(attempt, retry_after)
            print(
                f"[llm-{kind}] {node or 'llm'} 호출 실패 "
                f"(attempt {attempt}/{attempts}) — {delay}s 후 재시도"
            )
            sleep(delay)

    # 루프는 반드시 return 또는 raise 로 끝난다 (방어적 분기)
    raise LLMUnavailableError(
        "transient", "LLM 재시도 루프가 비정상 종료", node=node, attempts=attempts
    )

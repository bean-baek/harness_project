"""
harness/router.py
─────────────────
LangGraph 조건부 엣지 라우터 함수 모음

논문 근거 (P-18):
  - 에이전트 상태를 평가하여 다음 노드를 결정한다.
  - 'continue' / 'reflect' / 'human' / 'done' 중 하나를 반환한다.
  - iteration >= max_retry 또는 IRREVERSIBLE 도구 호출 예정 시 'human'으로 분기.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, ToolMessage

import config
from harness.state import HarnessState


# ReAct 루프 하드 캡 — 분석 마비(탐색만 반복) 방어용 안전망
MAX_TOOL_CALLS_PER_FEATURE = 15

#: ToolMessage 내용에서 **실패**를 식별하는 패턴 (TS-018).
#:
#: 왜 한국어 마커가 필요한가 — 실측:
#:   `harness/tools.py` 의 도구들은 실패를 **예외로 올리지 않고 문자열로 반환**한다.
#:   그 문자열은 전부 `[오류]` / `[보안 오류]` 로 시작하는 한국어다 — 16건 중
#:   영어 오류 키워드를 포함한 것은 **0건**이었다. 따라서 영어만 보는 정규식은
#:   `status == "error"`(예외를 올린 경우)만 잡고, **반환된 실패는 전부 놓쳤다.**
#:   결과: 도구 실패에 대해 Reflexion 루프가 한 번도 작동하지 않았다.
#:
#: `[거부]` 는 **일부러 제외**한다. 증거 게이트의 거부는 장애가 아니라 **판정**이고
#: (TS-006/TS-008), 코더가 ToolMessage 로 사유를 받아 다음 턴에 스스로 대응하는 것이
#: 설계다. 거부를 오류로 취급하면 정상적인 게이트 작동마다 Reflexion 이 돌아
#: 재시도 예산(max_retry)을 소모한다.
TOOL_FAILURE_RE = re.compile(
    r"\b(?:Error|Exception|Traceback|FAIL(?:ED)?)\b"
    r"|\[(?:오류|보안 오류)\]",
    re.I,
)


# ── 라우터: START 이후 초기화 여부 판단 ────────────────────────────────────

def route_initial(state: HarnessState) -> str:
    """
    첫 실행 시 Initializer 노드로, 이미 초기화된 경우 Orchestrator 노드로 분기.
    """
    import os
    project_root = state.get("project_root", ".")
    features_exists = os.path.exists(os.path.join(project_root, "features.json"))
    progress_exists = os.path.exists(os.path.join(project_root, "gemini-progress.txt"))

    if features_exists and progress_exists:
        return "orchestrator"
    return "initializer"


# ── 라우터: Orchestrator 이후 분기 — 도구 호출이 있으면 act 로 ─────────────

def route_after_orchestrator(state: HarnessState) -> str:
    """
    Orchestrator가 `read_features` 등의 도구를 호출한 경우 그 결과를 실제로 얻기 위해
    act → reason 으로 흘러야 한다. 도구 호출이 없으면 바로 reason 으로.
    """
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            for tc in last.tool_calls:
                if _is_irreversible(tc.get("name", "")):
                    return "human_check"
            return "act"
    return "reason"


# ── 라우터: 추론(Reason) 노드 이후 분기 ────────────────────────────────────

def route_after_reason(state: HarnessState) -> str:
    """
    ReAct Thought 단계 이후 분기:
      - 도구 호출 요청이 있으면 → 'act' (IRREVERSIBLE 시 'human_check')
      - 도구 호출 없음 + ToolMessage 이력 0개 + 첫 턴 → 'no_progress_guard' (silent-abort)
      - 도구 호출 없음 + 이미 작업 이력 있음 → 'evaluate' (Coder 작업 완료 선언)
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage):
        if getattr(last_msg, "tool_calls", None):
            for tc in last_msg.tool_calls:
                if _is_irreversible(tc.get("name", "")):
                    return "human_check"
            return "act"

    # tool_calls 없는 AI 응답 → 완료 선언 or silent-abort
    has_tool_history = any(isinstance(m, ToolMessage) for m in messages)

    # 물리적 증거가 없으면 절대 Evaluator 로 보내지 않는다 —
    # iteration/reflection 상태 무관, 항상 no_progress_guard 로 보내 Reflexion 루프에 태움.
    if not has_tool_history:
        return "no_progress_guard"

    # 증거 존재 — Evaluator 로
    return "evaluate"


# ── 라우터: 행동(Act) 노드 이후 분기 (P-18 핵심) ───────────────────────────

def route_after_act(state: HarnessState) -> str:
    """
    ReAct Action 단계 이후 분기 (P-18 라우팅).

    판단 기준:
      'human_check' → pending_approval 플래그 set
      'escalate'    → iteration >= max_retry
      'reflect'     → 실제 오류 발생
      'evaluate'    → tool_call 누적이 MAX_TOOL_CALLS_PER_FEATURE 초과 (안전망)
      'continue'    → 기본 — reason 으로 복귀, ReAct 루프 지속
    """
    messages         = state.get("messages", [])
    iteration        = state.get("iteration", 0)
    max_retry        = state.get("max_retry", 5)
    error_log        = state.get("error_log", [])
    pending_approval = state.get("pending_approval", False)

    # silent-abort 마커는 act-time 오류가 아니므로 reflect 트리거에서 제외
    real_errors = [e for e in error_log if not str(e).startswith("[silent-abort]")]

    # 최근 ToolMessage 의 에러 상태/내용을 스캔 — LLM 텍스트에만 의존하지 않는다
    for m in messages[-5:]:
        if isinstance(m, ToolMessage):
            if getattr(m, "status", None) == "error":
                real_errors.append(f"[tool:{getattr(m, 'name', '?')}] {str(m.content)[:400]}")
                continue
            content = m.content if isinstance(m.content, str) else str(m.content)
            if TOOL_FAILURE_RE.search(content):
                real_errors.append(f"[tool:{getattr(m, 'name', '?')}] {content[:400]}")

    # 누적 tool_call 수 계산 — 쓰기 없는 탐색 루프 폭주 방어
    tool_call_count = sum(
        len(getattr(m, "tool_calls", []) or [])
        for m in messages
        if isinstance(m, AIMessage)
    )

    if pending_approval:
        return "human_check"
    if iteration >= max_retry:
        return "escalate"
    if real_errors:
        return "reflect"
    if tool_call_count >= MAX_TOOL_CALLS_PER_FEATURE:
        return "evaluate"
    return "continue"


# ── 라우터: 평가(Evaluate) 노드 이후 분기 ──────────────────────────────────

def route_after_evaluate(state: HarnessState) -> str:
    """
    Evaluator 노드 이후 분기:
      - PASS (config.EVAL_PASS_THRESHOLD 이상) → 'done' (세션 핸드오프 후 완료)
      - FAIL                                   → 'reflect' (Reflexion 루프)

    임계값을 하드코딩하지 않는 이유 (TS-019): 여기에 `75` 가 박혀 있었고
    `config.EVAL_PASS_THRESHOLD`(= `HARNESS_EVAL_THRESHOLD`)는 **어디서도 읽히지
    않았다.** README 는 그 환경변수를 "Evaluator 합격선"으로 광고하고 있었다 —
    설정을 바꿔도 아무 일이 없는 TS-007 과 똑같은 구조다.
    """
    verdict = state.get("evaluation_verdict", "FAIL")
    score   = state.get("evaluation_score", 0)
    iteration = state.get("iteration", 0)
    max_retry = state.get("max_retry", 5)

    if verdict == "PASS" and score >= config.EVAL_PASS_THRESHOLD:
        return "done"

    # 재시도 한도 초과
    if iteration >= max_retry:
        return "escalate"

    return "reflect"


# ── 라우터: 반성(Reflect) 노드 이후 분기 ───────────────────────────────────

def route_after_reflect(state: HarnessState) -> str:
    """
    Reflector 노드 이후 분기:
      - confidence < 30% → 인간 에스컬레이션
      - 그 외            → 'reason' (재시도)
    """
    pending_approval = state.get("pending_approval", False)
    if pending_approval:
        return "human_check"
    return "reason"


# ── 라우터: Human Check 이후 분기 ──────────────────────────────────────────

def route_after_human_check(state: HarnessState) -> str:
    """
    인간 체크 노드 이후 분기:
      - 승인됨 → 'reason' (재개)
      - 취소됨 → '__end__'
    """
    status = state.get("status", "")
    if status == "cancelled":
        return "__end__"
    return "reason"


# ── 헬퍼 ───────────────────────────────────────────────────────────────────

def _is_irreversible(tool_name: str) -> bool:
    """도구 이름이 IRREVERSIBLE 계층인지 확인한다."""
    from harness.tools import TOOL_REGISTRY
    return TOOL_REGISTRY.get(tool_name, "STATEFUL") == "IRREVERSIBLE"

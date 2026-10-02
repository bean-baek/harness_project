"""
harness/nodes/agents.py
───────────────────────
5개 에이전트 노드 함수 전체 구현

논문 근거:
  P-01 Orchestrator  → orchestrator_node
  P-02 Initializer   → initializer_node
  P-03 Coder         → coder_node (ReAct + Reflexion 주입)
  P-04 Evaluator     → evaluator_node (GAN 구조 판별자)
  P-05 Reflector     → reflector_node (5-Why + 에피소드 메모리)
"""

from __future__ import annotations

import re
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.types import interrupt, Command

# 첫 턴에 도구 호출 없이 끝난 뒤 재진입할 때 주입하는 강제 도구 호출 넛지
_TOOL_CALL_NUDGE = (
    "다음 응답에서 반드시 하나 이상의 도구를 호출하십시오. "
    "어떤 도구를 쓸지 모르겠다면 `read_features(project_root)` 또는 "
    "`list_directory(path)` 부터 호출해 현재 프로젝트 상태를 파악하십시오. "
    "텍스트만으로 답하지 마십시오."
)

from harness.state import HarnessState
from harness.prompts import (
    P01_ORCHESTRATOR,
    P02_INITIALIZER,
    P03_CODER,
    P04_EVALUATOR,
    P05_REFLECTOR,
    P06_REACT_BASIC,
    P07_CODING_REACT,
    P09_SELF_EVALUATION,
    P20_APPROVAL_REQUEST,
    P21_ESCALATION_REPORT,
    P08_REFLEXION_INJECT,
    build_coder_system_prompt,
    build_coder_user_message,
)
from harness.tools import (
    CODER_TOOLS,
    INITIALIZER_TOOLS,
    ORCHESTRATOR_TOOLS,
)
from harness.memory import load_episodic_memory, save_episodic_memory
from harness.llm_errors import invoke_llm
from harness.state import RESET_SENTINEL
import config


# ── LLM 초기화 ──────────────────────────────────────────────────────────────

def _get_llm(model: str = config.LLM_MODEL) -> ChatGoogleGenerativeAI:
    """ChatGoogleGenerativeAI 인스턴스를 반환한다.

    timeout/max_retries 를 명시하지 않으면 네트워크 이슈 시 무한 대기할 수 있어
    파이프 출력 버퍼링과 결합되면 전체 하네스가 조용히 hang 된다.
    """
    return ChatGoogleGenerativeAI(
        model=model,
        max_tokens=4096,
        google_api_key=config.GOOGLE_API_KEY,
        timeout=120,        # 단일 호출 최대 2분
        max_retries=2,      # 일시 오류 시 최대 2회 재시도
    )


# ══════════════════════════════════════════════════════════════════════════════
# P-01: Orchestrator 노드
# ══════════════════════════════════════════════════════════════════════════════

def orchestrator_node(state: HarnessState) -> dict[str, Any]:
    """
    전체 워크플로우를 조율하는 최상위 에이전트 노드.

    - features.json에서 다음 작업을 선택한다.
    - 서브에이전트에게 원자적 작업 단위를 위임한다.
    - 비가역적 작업에는 인간 승인 플래그를 설정한다.
    """
    llm = _get_llm()
    llm_with_tools = llm.bind_tools(ORCHESTRATOR_TOOLS)

    from string import Template
    system = Template(P01_ORCHESTRATOR).safe_substitute(
        project_root=state.get("project_root", "./"),
        current_sprint="Sprint-1",
        completed_features=sum(
            1 for f in []  # features.json은 read_features 도구로 읽음
        ),
        total_features=200,
        max_retry=state.get("max_retry", 5),
    )

    messages = [HumanMessage(content=system)] + state["messages"]
    response = invoke_llm(llm_with_tools, messages, node="orchestrator")

    return {
        "messages": [response],
        "status": "reasoning",
    }


# ══════════════════════════════════════════════════════════════════════════════
# P-02: Initializer 노드
# ══════════════════════════════════════════════════════════════════════════════

def initializer_node(state: HarnessState) -> dict[str, Any]:
    """
    첫 번째 세션에서만 실행되는 환경 초기화 에이전트.

    생성 아티팩트:
      - init.sh, features.json, gemini-progress.txt
      - 초기 git 커밋, README.md
    """
    llm = _get_llm()
    llm_with_tools = llm.bind_tools(INITIALIZER_TOOLS)

    # ReAct 모듈 추가
    system = P02_INITIALIZER + "\n\n" + P06_REACT_BASIC

    messages = [HumanMessage(content=system)] + state["messages"]
    response = invoke_llm(llm_with_tools, messages, node="initializer")

    return {
        "messages": [response],
        "status": "initializing",
    }


# ══════════════════════════════════════════════════════════════════════════════
# P-03: Coder 노드 (ReAct + Reflexion)
# ══════════════════════════════════════════════════════════════════════════════

def coder_node(state: HarnessState) -> dict[str, Any]:
    """
    증분적 기능 구현 에이전트.

    핵심 설계:
      1. ReAct 루프 강제 (P-07): Thought → Action → Observation
      2. Reflexion 주입 (P-08): 재시도 시 에피소드 메모리를 컨텍스트에 삽입
      3. 자기 평가 (P-09): 완료 선언 전 4가지 Q&A 검증
    """
    llm = _get_llm()
    llm_with_tools = llm.bind_tools(CODER_TOOLS)

    # 시스템 프롬프트 조립 (P-03 + P-07 + P-09)
    system = build_coder_system_prompt(with_react=True, with_self_eval=True)

    # 메시지 조립: 재시도 시 Reflexion 메모리 주입 (P-08)
    messages = list(state["messages"])
    reflections = state.get("reflections", [])
    iteration = state.get("iteration", 0)
    prev_errors = state.get("error_log", []) or []
    had_silent_abort = any("[silent-abort]" in e for e in prev_errors)

    if reflections and iteration > 0:
        # 에피소드 메모리를 마지막 HumanMessage 앞에 삽입
        inject = HumanMessage(
            content=P08_REFLEXION_INJECT(
                attempt_count=iteration,
                current_task=state.get("task", ""),
                reflections=reflections,
            )
        )
        # 마지막 HumanMessage 위치 찾기
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if isinstance(messages[i], HumanMessage)),
            len(messages),
        )
        messages.insert(last_human_idx, inject)

    # 이전 턴이 silent-abort 였거나 재시도 중이면 도구 호출 넛지 주입
    if had_silent_abort or (reflections and iteration > 0):
        messages.append(HumanMessage(content=_TOOL_CALL_NUDGE))

    # SystemMessage 로 시스템 프롬프트 전달 → Gemini 의 system_instruction 에 매핑됨
    full_messages = [SystemMessage(content=system)] + messages
    response = invoke_llm(llm_with_tools, full_messages, node="reason(coder)")

    # 오류 감지: ESLint/TypeScript/Jest 오류 패턴
    error_log = []
    content = response.content if isinstance(response.content, str) else ""
    error_patterns = [
        r"error TS\d+:",
        r"\d+ errors?",
        r"FAIL.*\.test\.",
        r"✗|✕|×",
    ]
    for pattern in error_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            error_log.append(content[:500])  # 오류 메시지 앞 500자 저장
            break

    return {
        "messages": [response],
        "status": "acting",
        "error_log": error_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# P-04: Evaluator 노드 (GAN 구조 판별자)
# ══════════════════════════════════════════════════════════════════════════════

def evaluator_node(state: HarnessState) -> dict[str, Any]:
    """
    Coder 결과물을 독립적으로 평가하는 에이전트.

    평가 기준: 기능성(40) + 코드품질(30) + 성능(20) + 보안(10)
    합격 기준: 75점 이상
    """
    # Evaluator는 act 루프가 없으므로 도구를 바인딩하지 않는다 —
    # Coder가 남긴 ToolMessage 히스토리를 보고 바로 점수/판정을 XML 태그로 내야 한다.
    llm = _get_llm()

    system = P04_EVALUATOR

    # 히스토리에서 ToolMessage의 출력만 요약하여 Evaluator 프롬프트에 직접 주입 —
    # tool_calls 패턴을 모방해 tool_call을 뱉는 것을 방지한다.
    tool_outputs: list[str] = []
    for m in state["messages"]:
        if isinstance(m, ToolMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
            tool_outputs.append(f"[Tool: {getattr(m, 'name', '?')}]\n{text[:1500]}")

    # 증거 0건이면 LLM 호출 없이 즉시 FAIL 처리 — Reflexion 루프로 곧장 복귀
    if not tool_outputs:
        return {
            "evaluation_score": 0,
            "evaluation_verdict": "FAIL",
            "evaluation_findings": [
                "Coder가 어떤 도구도 실행하지 않음 — 구현 증거가 없어 평가 불가",
            ],
            "status": "evaluating",
            "error_log": ["[no-evidence] evaluator bypassed — no ToolMessage in history"],
        }

    evidence = "\n\n".join(tool_outputs)

    prompt = (
        f"다음 작업에 대한 Coder의 실행 증거를 판정하십시오.\n\n"
        f"## 작업\n{state.get('task', '')}\n\n"
        f"## Coder의 도구 실행 기록\n{evidence}\n\n"
        f"## 출력 규칙\n"
        f"반드시 아래 세 태그를 포함한 평문으로만 응답하십시오. 도구를 호출하지 마십시오.\n"
        f"<score>N/100</score>\n"
        f"<verdict>PASS 또는 FAIL</verdict>\n"
        f"<critical>- 발견사항1\\n- 발견사항2</critical>\n"
    )

    response = invoke_llm(
        llm,
        [SystemMessage(content=system), HumanMessage(content=prompt)],
        node="evaluate",
    )

    # 평가 결과 파싱
    content = response.content if isinstance(response.content, str) else ""
    score = _parse_score(content)
    verdict = _parse_verdict(content)
    findings = _parse_findings(content)

    return {
        "messages": [response],
        "evaluation_score": score,
        "evaluation_verdict": verdict,
        "evaluation_findings": findings,
        "status": "evaluating",
    }


def _parse_score(content: str) -> int:
    # 1순위: <score>N/100</score> 또는 <score>N</score>
    m = re.search(r"<score>\s*(\d+)\s*(?:/\s*100)?\s*</score>", content, re.I)
    if m:
        return min(int(m.group(1)), 100)
    # 2순위: "점수: 82", "score: 82", "82/100"
    m = re.search(r"(?:점수|score)\s*[:=]?\s*(\d+)(?:\s*/\s*100)?", content, re.I)
    if m:
        return min(int(m.group(1)), 100)
    m = re.search(r"\b(\d{1,3})\s*/\s*100\b", content)
    return min(int(m.group(1)), 100) if m else 0

def _parse_verdict(content: str) -> str:
    m = re.search(r"<verdict>\s*(PASS|FAIL)\s*</verdict>", content, re.I)
    if m:
        return m.group(1).upper()
    # fallback: 본문에서 PASS/FAIL 키워드
    if re.search(r"\b(PASS|합격|통과)\b", content, re.I):
        return "PASS"
    return "FAIL"

def _parse_findings(content: str) -> list[str]:
    """<critical>...</critical> 패턴에서 발견 사항 추출."""
    match = re.search(r"<critical>(.*?)</critical>", content, re.DOTALL)
    if not match:
        return []
    text = match.group(1).strip()
    return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# P-05: Reflector 노드 (5-Why + 에피소드 메모리)
# ══════════════════════════════════════════════════════════════════════════════

def _tool_failures_from(messages: list, limit: int = 5) -> str:
    """최근 메시지에서 **실패한 ToolMessage** 를 뽑아 Reflector 가 읽을 형태로 만든다.

    판정 기준은 `router.TOOL_FAILURE_RE` 와 동일하다 — 라우터가 'reflect 로 보낸다'고
    판단한 것과 Reflector 가 '이게 실패다'라고 읽는 것이 어긋나면 안 된다.
    한쪽만 고치면 다시 신호 없는 반성이 된다.
    """
    from harness.router import TOOL_FAILURE_RE

    out: list[str] = []
    for m in reversed(messages):
        if not isinstance(m, ToolMessage):
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        if getattr(m, "status", None) == "error" or TOOL_FAILURE_RE.search(content):
            out.append(f"[tool:{getattr(m, 'name', '?')}] {content[:400]}")
        if len(out) >= limit:
            break
    return "\n".join(reversed(out))


def reflector_node(state: HarnessState) -> dict[str, Any]:
    """
    실패 원인을 분석하고 다음 시도 전략을 생성하는 에이전트.

    Reflexion (Shinn et al., 2023) 구현:
      - 5-Why 방법론으로 근본 원인 분석
      - 에피소드 메모리에 반성 기록 저장
      - confidence < 30%이면 인간 에스컬레이션 권고
    """
    llm = _get_llm()

    error_ctx = "\n".join(state.get("error_log", [])[-5:])
    # error_log 가 비어 있어도 **도구가 실패해서 여기 왔을 수 있다** (TS-018).
    #
    # 실측: `route_after_act` 는 실패한 ToolMessage 를 감지해 reflect 로 보내지만,
    # 라우터는 상태를 쓰지 않으므로 그 실패 내용이 어디에도 기록되지 않는다.
    # `coder_node` 의 오류 스캔은 **LLM 응답 본문**만 보고, 그것은 act 이전이다.
    # 결과: 도구가 실패해서 Reflexion 이 돌았는데도 프롬프트에는
    # "직접적인 오류 로그 없음" 이 들어갔다 — Reflector 가 신호 없이 반성했다.
    #
    # 보관된 F-004 증거("정보 없는 오류 신호에서 Reflexion 이 작화한다")의 기계적 원인이
    # 이것이다. 신호가 비유사했던 게 아니라 **아예 없었다.**
    if not error_ctx:
        error_ctx = _tool_failures_from(state.get("messages", []))
    prev_reflections = "\n".join(state.get("reflections", [])[-3:])
    iteration = state.get("iteration", 0)
    findings = "\n".join(state.get("evaluation_findings", []))

    reflection_prompt = f"""
{P05_REFLECTOR}

<input>
  <attempt_number>{iteration}</attempt_number>
  <failed_task>{state.get("task", "알 수 없음")}</failed_task>
  <error_log>{error_ctx or "직접적인 오류 로그 없음"}</error_log>
  <evaluator_feedback>{findings or "평가 피드백 없음"}</evaluator_feedback>
  <previous_reflections>{prev_reflections or "없음"}</previous_reflections>
</input>
"""

    response = invoke_llm(llm, [HumanMessage(content=reflection_prompt)], node="reflect")
    content = response.content if isinstance(response.content, str) else ""

    # confidence 파싱 → 30% 미만이면 에스컬레이션 플래그
    confidence = _parse_confidence(content)
    should_escalate = confidence < 30 and iteration >= 2

    # 에피소드 메모리 저장
    save_episodic_memory(
        session_id=state.get("session_id", "default"),
        reflection=content,
        iteration=iteration,
    )

    return {
        "messages": [response],
        "reflections": [content],
        "error_log": [RESET_SENTINEL],            # 오류 로그 초기화 (reducer가 sentinel 처리)
        "iteration": iteration + 1,
        "status": "reflecting",
        "pending_approval": should_escalate,       # 에스컬레이션 플래그
        "pending_action": {
            "type": "escalation",
            "reason": f"Reflexion confidence {confidence}% — 근본 원인 불명확",
        } if should_escalate else {},
    }


def _parse_confidence(content: str) -> int:
    """<confidence>N%</confidence> 패턴에서 신뢰도 추출."""
    match = re.search(r"<confidence>(\d+)%?</confidence>", content)
    return int(match.group(1)) if match else 50


# ══════════════════════════════════════════════════════════════════════════════
# Human-in-the-Loop 노드 (P-20, P-21)
# ══════════════════════════════════════════════════════════════════════════════

def human_check_node(state: HarnessState) -> dict[str, Any] | Command:
    """
    비가역적 작업 또는 에스컬레이션 전 인간 승인 대기 노드.

    interrupt()를 사용하여 그래프 실행을 일시 정지한다.
    체크포인터가 반드시 설정되어 있어야 한다.
    """
    pending_action = state.get("pending_action", {})

    # 승인 요청 메시지 생성 (P-20)
    approval_msg = P20_APPROVAL_REQUEST(
        action_description=pending_action.get("type", "알 수 없음"),
        scope=pending_action.get("scope", "미정"),
        tool_name=pending_action.get("tool", "미정"),
        expected_outcome=pending_action.get("expected", "미정"),
        rollback_possible=pending_action.get("rollback_possible", False),
        rollback_procedure=pending_action.get("rollback", ""),
    )

    # interrupt(): 여기서 그래프 실행 일시 정지
    # 외부에서 Command(resume={"approved": True/False, "instruction": "..."}) 로 재개
    decision = interrupt({
        "message": approval_msg,
        "state_snapshot": {
            "task": state.get("task"),
            "iteration": state.get("iteration"),
            "pending_action": pending_action,
        },
    })

    approved = decision.get("approved", False)
    instruction = decision.get("instruction", "")

    if approved:
        return {
            "pending_approval": False,
            "pending_action": {},
            "status": "reasoning",
            "metadata": {"human_approved": True, "instruction": instruction},
        }
    else:
        return Command(
            goto="__end__",
            update={
                "status": "cancelled",
                "metadata": {"cancelled_by_human": True, "reason": instruction},
            },
        )


def escalate_node(state: HarnessState) -> dict[str, Any]:
    """
    최대 재시도 초과 시 인간에게 에스컬레이션 보고서를 전달한다 (P-21).
    """
    report = P21_ESCALATION_REPORT(
        reason="최대 재시도 횟수 초과" if state.get("iteration", 0) >= state.get("max_retry", 5)
               else "해결 불가 기술적 문제",
        attempt_count=state.get("iteration", 0),
        max_retry=state.get("max_retry", 5),
        tried=[
            {"attempt": i + 1, "description": r[:100], "result": "FAIL"}
            for i, r in enumerate(state.get("reflections", []))
        ],
        last_good_commit=state.get("last_good_commit", ""),
        modified_files=[],     # 실제 환경: git diff --name-only 결과
        decisions_needed=[
            "코드를 직접 수정하여 재시도하시겠습니까?",
            "다른 접근 방식을 지정하시겠습니까?",
            "이 기능 구현을 보류하시겠습니까?",
        ],
        recommendation=(
            "마지막 성공 커밋으로 롤백 후 "
            "수동 코드 리뷰를 권장합니다."
        ),
    )

    print(report)  # 실제 환경: Slack/이메일 알림

    return {
        "status": "escalated",
        "messages": [AIMessage(content=report)],
    }

"""
harness/graph.py
────────────────
LangGraph StateGraph 전체 구성 — 하네스 핵심

논문 근거 (Section 4.3):
  - StateGraph: 에이전트의 모든 실행 상태를 타입화된 딕셔너리로 관리
  - Breakpoint + Human-in-the-Loop: interrupt_before 옵션으로 구현
  - 감사 가능성: 모든 상태 전이가 체크포인터에 저장됨
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode

from harness.state import HarnessState
from harness.nodes.agents import (
    orchestrator_node,
    initializer_node,
    coder_node,
    evaluator_node,
    reflector_node,
    human_check_node,
    escalate_node,
)
from harness.router import (
    route_initial,
    route_after_reason,
    route_after_act,
    route_after_evaluate,
    route_after_reflect,
    route_after_human_check,
    route_after_orchestrator,
)
from harness.tools import CODER_TOOLS


# ── 세션 완료 노드 ───────────────────────────────────────────────────────────

def session_done_node(state: HarnessState) -> dict:
    """
    기능 구현 완료 후 세션을 정리하는 노드.
    - gemini-progress.txt 핸드오프 기록
    - git commit
    """
    from harness.prompts import P17_SESSION_HANDOFF
    from harness.tools import write_progress, git_commit

    handoff = P17_SESSION_HANDOFF(
        session_id=state.get("session_id", "unknown"),
        feature_name=state.get("task", ""),
        result="PASS",
        completed=[state.get("task", "")],
        incomplete=[],
        critical_context=[
            f"평가 점수: {state.get('evaluation_score', 0)}/100",
            f"반복 횟수: {state.get('iteration', 0)}",
        ],
        next_first_step="features.json에서 다음 미완성 기능을 선택하여 구현하십시오.",
        warnings=[],
    )

    project_root = state.get("project_root", ".")
    write_progress.invoke({"project_root": project_root, "content": handoff})
    git_commit.invoke({
        "project_root": project_root,
        "message": f"chore: 세션 {state.get('session_id', 'unknown')} 핸드오프 기록",
        "files": ["gemini-progress.txt"],
    })

    return {"status": "done"}


# ── Silent-abort 가드 노드 ────────────────────────────────────────────────────

def _build_checkpointer(use_persistent_memory: bool, db_uri: str | None):
    """체크포인터를 생성한다 — 영속 백엔드 실패 시 **소리내어** InMemorySaver 로 폴백.

    TS-007 배경:
      - main.py 가 플래그를 전달하지 않아 이 분기는 한 번도 실행되지 않았다.
      - `PostgresSaver.from_conn_string()` 은 컨텍스트 매니저라 그대로 대입하면
        체크포인터가 아닌 _GeneratorContextManager 가 들어가 런타임에 깨진다.
        그래프가 블록보다 오래 살아야 하므로 명시적으로 __enter__() 하고
        프로세스 생명주기 동안 유지한다.
      - 조용한 폴백은 금물이다. InMemorySaver 로 떨어지면 프로세스 간 재개가 불가능하고
        human_check 의 interrupt() 상태도 프로세스와 함께 사라진다 — 운영자가 알아야 한다.
    """
    if not use_persistent_memory:
        return InMemorySaver()

    if not db_uri:
        print("[경고] HARNESS_PERSISTENT=true 이지만 DATABASE_URL 이 비어 있습니다 "
              "— InMemorySaver 로 폴백 (프로세스 간 재개 불가)")
        return InMemorySaver()

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        print("[경고] langgraph-checkpoint-postgres 미설치 — InMemorySaver 로 폴백 "
              "(프로세스 간 재개 불가). 활성화: "
              "pip install langgraph-checkpoint-postgres psycopg[binary]")
        return InMemorySaver()

    try:
        # from_conn_string 은 @contextmanager — 그래프 수명이 더 길므로 직접 진입한다.
        manager = PostgresSaver.from_conn_string(db_uri)
        checkpointer = manager.__enter__()
        checkpointer.setup()                      # 최초 실행 시 테이블 생성
        _PERSISTENT_MANAGERS.append(manager)      # GC 로 닫히지 않게 참조 유지
        print("[체크포인터] PostgresSaver 활성 — 세션 간 재개 가능")
        return checkpointer
    except Exception as exc:                      # noqa: BLE001 — 폴백 후 계속 진행
        print(f"[경고] PostgresSaver 초기화 실패 ({type(exc).__name__}: {exc}) "
              "— InMemorySaver 로 폴백 (프로세스 간 재개 불가)")
        return InMemorySaver()


#: 열린 체크포인터 컨텍스트 매니저 — 프로세스 종료까지 참조를 유지한다.
_PERSISTENT_MANAGERS: list = []


def no_progress_guard_node(state: HarnessState) -> dict:
    """
    Coder 가 첫 턴에 도구 호출 없이 텍스트만 응답한 경우 진입하는 노드.

    그래프가 조용히 종료되는 걸 막기 위해 error_log 에 마커를 기록하고
    reflect 노드로 라우팅시켜 Reflexion 루프에 태운다.
    """
    return {
        "status": "no_progress",
        "error_log": ["[silent-abort] coder returned no tool calls on first turn"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 메인 하네스 그래프 빌더
# ══════════════════════════════════════════════════════════════════════════════

def build_harness_graph(
    max_retry: int = 5,
    use_persistent_memory: bool = False,
    db_uri: str | None = None,
) -> "CompiledStateGraph":
    """
    하네스 엔지니어링 완전 구현 그래프를 생성하고 반환한다.

    Args:
        max_retry:              최대 Reflexion 반복 횟수 (기본: 5)
        use_persistent_memory:  PostgreSQL 체크포인터 사용 여부
        db_uri:                 PostgreSQL 연결 문자열 (use_persistent_memory=True 시 필요)

    Returns:
        컴파일된 StateGraph (invoke/stream/ainvoke 사용 가능)

    노드 구성:
      initializer  → coder → act(ToolNode) → evaluate → reflect → human_check → escalate
                                ↑_____________________________________↓ (Reflexion 루프)

    상태 전이도 (논문 Section 5.4):
      START          → [route_initial] → initializer / orchestrator
      initializer    → reason
      orchestrator   → reason
      reason         → [route_after_reason] → act / human_check / END
      act (ToolNode) → [route_after_act]    → continue / reflect / human_check / escalate / evaluate
      evaluate       → [route_after_evaluate] → done / reflect / escalate
      reflect        → [route_after_reflect]  → reason / human_check
      human_check    → [route_after_human_check] → reason / END
      escalate       → END
      done           → END
    """
    graph = StateGraph(HarnessState)

    # ── 노드 등록 ──────────────────────────────────────────────────────────

    # 환경 초기화 에이전트 (P-02)
    graph.add_node("initializer", initializer_node)

    # 조율자 에이전트 (P-01)
    graph.add_node("orchestrator", orchestrator_node)

    # ReAct Thought 단계 — Coder (P-03)
    graph.add_node("reason", coder_node)

    # ReAct Action 단계 — ToolNode (도구 실행)
    graph.add_node("act", ToolNode(
        tools=CODER_TOOLS,
        handle_tool_errors=True,   # 예외를 ToolMessage로 변환
        name="act",
    ))

    # GAN 판별자 — Evaluator (P-04)
    graph.add_node("evaluate", evaluator_node)

    # Reflexion 반성 에이전트 (P-05)
    graph.add_node("reflect", reflector_node)

    # Human-in-the-Loop 승인 노드 (P-20)
    graph.add_node("human_check", human_check_node)

    # 에스컬레이션 노드 (P-21)
    graph.add_node("escalate", escalate_node)

    # 세션 완료 핸드오프 노드 (P-17)
    graph.add_node("done", session_done_node)

    # Silent-abort 가드 — 첫 턴에 도구 호출 없이 끝나는 케이스 방어
    graph.add_node("no_progress_guard", no_progress_guard_node)

    # ── 엣지 연결 ──────────────────────────────────────────────────────────

    # START → 초기화 여부에 따라 분기
    graph.add_conditional_edges(
        START,
        route_initial,
        {
            "initializer": "initializer",
            "orchestrator": "orchestrator",
        }
    )

    # 초기화 → 추론
    graph.add_edge("initializer", "reason")

    # 조율자 → 도구 호출이 있으면 act 거쳐서 reason, 없으면 직접 reason
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "act":         "act",
            "reason":      "reason",
            "human_check": "human_check",
        }
    )

    # Thought 단계 → 도구 호출 여부로 분기
    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "act":                "act",
            "human_check":        "human_check",
            "no_progress_guard":  "no_progress_guard",
            "evaluate":           "evaluate",
            "__end__":            END,
        }
    )

    # Silent-abort 가드 → 바로 reflect 로 보내 Reflexion 루프 가동
    graph.add_edge("no_progress_guard", "reflect")

    # Action 단계 → 결과에 따라 분기 (P-18 핵심 라우팅)
    graph.add_conditional_edges(
        "act",
        route_after_act,
        {
            "continue":    "reason",      # 성공 → 다음 기능
            "reflect":     "reflect",     # 오류 → Reflexion
            "human_check": "human_check", # 비가역적 작업
            "escalate":    "escalate",    # 최대 재시도 초과
            "evaluate":    "evaluate",    # 평가 요청
        }
    )

    # 평가 결과에 따라 분기
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "done":     "done",
            "reflect":  "reflect",
            "escalate": "escalate",
        }
    )

    # Reflexion 완료 → 재시도 또는 에스컬레이션
    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "reason":     "reason",
            "human_check": "human_check",
        }
    )

    # 인간 체크 완료 → 재개 또는 종료
    graph.add_conditional_edges(
        "human_check",
        route_after_human_check,
        {
            "reason":  "reason",
            "__end__": END,
        }
    )

    # 에스컬레이션, 완료 → 종료
    graph.add_edge("escalate", END)
    graph.add_edge("done",     END)

    # ── 체크포인터 설정 ────────────────────────────────────────────────────

    checkpointer = _build_checkpointer(use_persistent_memory, db_uri)

    # ── 컴파일 — interrupt_before로 human_check 전 자동 일시정지 ──────────

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_check"],   # 비가역적 작업 전 자동 정지
        interrupt_after=[],
    )


# ── 그래프 시각화 헬퍼 ────────────────────────────────────────────────────────

def visualize_graph(app, output_path: str = "harness_graph.png") -> None:
    """
    Mermaid PNG로 그래프를 시각화한다.
    IPython 환경에서는 인라인 표시.
    """
    try:
        png = app.get_graph().draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png)
        print(f"그래프 저장됨: {output_path}")
    except Exception as e:
        print(f"시각화 실패: {e}")
        # Mermaid 텍스트로 대체 출력
        print(app.get_graph().draw_mermaid())

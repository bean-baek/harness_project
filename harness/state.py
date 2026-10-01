"""
harness/state.py
────────────────
하네스 엔지니어링 공유 상태(Shared State) 정의

논문 근거:
  - LangGraph StateGraph는 모든 노드가 읽고 쓰는 '공유 상태'를 중심으로 동작한다.
  - ReAct의 reasoning trace, Reflexion의 에피소드 메모리, Human-in-the-Loop의
    승인 플래그 등이 모두 이 State에 저장된다.
  - 에이전트 가이드: 각 키는 reducer를 통해 병렬/누적 업데이트를 지원한다.
"""

from __future__ import annotations

from typing import Annotated, Literal, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# ── 커스텀 Reducer 함수 ──────────────────────────────────────────────────────

def append_unique(existing: list, new: list | str) -> list:
    """중복 없이 리스트 누적. 에피소드 메모리에 사용."""
    items = new if isinstance(new, list) else [new]
    combined = existing.copy()
    for item in items:
        if item not in combined:
            combined.append(item)
    return combined


RESET_SENTINEL = "__RESET__"


def keep_last_n(n: int):
    """최근 N개만 유지하는 reducer 팩토리. 오류 로그 윈도우에 사용.

    리셋 규약: 새 값이 ``[RESET_SENTINEL]`` 단일 항목 리스트이면 기존 누적을 비운다.
    Reflector 가 다음 시도를 위해 오류 로그를 초기화할 때 사용한다.
    """
    def reducer(existing: list, new: list | str) -> list:
        items = new if isinstance(new, list) else [new]
        if items == [RESET_SENTINEL]:
            return []
        items = [x for x in items if x != RESET_SENTINEL]
        combined = existing + items
        return combined[-n:]
    return reducer


def merge_dict(existing: dict, new: dict) -> dict:
    """딕셔너리 얕은 병합. 메타데이터 업데이트에 사용."""
    return {**existing, **new}


def max_reducer(existing: int, new: int) -> int:
    """최대값 유지. 최고 점수 기록에 사용."""
    return max(existing, new)


# ── 주요 상태 Literal 타입 ───────────────────────────────────────────────────

AgentStatus = Literal[
    "idle",             # 초기 상태
    "initializing",     # 환경 초기화 중 (Initializer Agent)
    "reasoning",        # ReAct Thought 단계
    "acting",           # ReAct Action 단계 (도구 실행)
    "observing",        # ReAct Observation 단계
    "reflecting",       # Reflexion 자기 반성 단계
    "evaluating",       # Evaluator Agent 검증 중
    "awaiting_human",   # Human-in-the-Loop 승인 대기
    "escalated",        # 최대 재시도 초과 → 인간 에스컬레이션
    "done",             # 작업 완료
    "cancelled",        # 인간이 취소
    "failed",           # 복구 불가 실패
]

EvaluationVerdict = Literal["PASS", "FAIL", "SKIP"]

ToolPermission = Literal["READ_ONLY", "STATEFUL", "IRREVERSIBLE"]


# ── 메인 하네스 상태 ─────────────────────────────────────────────────────────

class HarnessState(TypedDict):
    """
    전체 하네스 공유 상태.

    ┌──────────────┬──────────────────────────────────────────────────┐
    │ 키 그룹       │ 설명                                              │
    ├──────────────┼──────────────────────────────────────────────────┤
    │ 대화          │ messages — LLM 대화 히스토리 (add_messages)        │
    │ 작업          │ task, feature_index, project_root                │
    │ 반복 제어      │ iteration, max_retry, status                     │
    │ Reflexion    │ reflections — 에피소드 메모리 (누적)                │
    │ 오류          │ error_log — 최근 10개 슬라이딩 윈도우               │
    │ 평가          │ evaluation_score, evaluation_verdict              │
    │ 인간 감독      │ pending_approval, pending_action                 │
    │ 메타데이터     │ session_id, metadata                             │
    └──────────────┴──────────────────────────────────────────────────┘
    """

    # ── 대화 히스토리 ──────────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    """LLM 대화 메시지. add_messages reducer로 자동 누적."""

    # ── 작업 컨텍스트 ──────────────────────────────────────────────────
    task: str
    """현재 구현 중인 기능 설명."""

    feature_index: int
    """features.json에서 현재 작업 중인 기능의 인덱스."""

    project_root: str
    """프로젝트 루트 절대 경로. Coder 에이전트가 항상 확인."""

    # ── 반복 제어 ──────────────────────────────────────────────────────
    iteration: int
    """현재 Reflexion 반복 횟수. max_retry 초과 시 에스컬레이션."""

    max_retry: int
    """최대 재시도 횟수. 기본값 5. 코딩 작업 권장: 5, 설계 작업: 3."""

    status: AgentStatus
    """현재 에이전트 상태. 라우터가 이 값을 읽어 분기 결정."""

    # ── Reflexion 에피소드 메모리 ──────────────────────────────────────
    reflections: Annotated[list[str], append_unique]
    """
    Reflexion 반성 메모 누적 목록.
    다음 시도 시 시스템 프롬프트에 주입되어 동일 실수를 방지한다.
    append_unique reducer로 중복 제거.
    """

    # ── 오류 로그 (슬라이딩 윈도우) ────────────────────────────────────
    error_log: Annotated[list[str], keep_last_n(10)]
    """
    최근 10개 오류 기록. 슬라이딩 윈도우로 컨텍스트 오염 방지.
    ESLint, TypeScript, Jest 오류 메시지가 여기에 저장된다.
    """

    # ── 평가 결과 ──────────────────────────────────────────────────────
    evaluation_score: Annotated[int, max_reducer]
    """Evaluator가 부여한 점수 (0-100). max_reducer로 최고 점수 기록."""

    evaluation_verdict: EvaluationVerdict
    """PASS (75점 이상) / FAIL / SKIP."""

    evaluation_findings: Annotated[list[str], append_unique]
    """Evaluator의 상세 발견 사항 (critical + minor)."""

    # ── Human-in-the-Loop ──────────────────────────────────────────────
    pending_approval: bool
    """True이면 다음 라우팅에서 human_check 노드로 이동."""

    pending_action: dict[str, Any]
    """
    승인 대기 중인 작업 상세 정보.
    예: {"tool": "deploy", "target": "production", "rollback": "git revert HEAD"}
    """

    # ── 세션 관리 ──────────────────────────────────────────────────────
    session_id: str
    """현재 세션 식별자. gemini-progress.txt 핸드오프 기록에 사용."""

    last_good_commit: str
    """마지막으로 성공한 git 커밋 해시. 에스컬레이션 시 롤백 기준."""

    # ── 메타데이터 ──────────────────────────────────────────────────────
    metadata: Annotated[dict[str, Any], merge_dict]
    """
    런타임 메타데이터. 여러 노드가 자유롭게 쓰고 merge_dict로 병합.
    예: {"lint_errors": 0, "test_coverage": 87, "lighthouse_score": 92}
    """


# ── 초기 상태 팩토리 ─────────────────────────────────────────────────────────

def create_initial_state(
    task: str,
    project_root: str,
    session_id: str,
    max_retry: int = 5,
    feature_index: int = 0,
) -> HarnessState:
    """
    하네스 실행 시작을 위한 기본 상태를 생성한다.

    Args:
        task:         구현할 기능 설명
        project_root: 프로젝트 루트 절대 경로
        session_id:   세션 식별자 (예: "session-001")
        max_retry:    최대 재시도 횟수 (기본: 5)
        feature_index: features.json 시작 인덱스 (기본: 0)

    Returns:
        초기화된 HarnessState 딕셔너리
    """
    return HarnessState(
        messages=[],
        task=task,
        feature_index=feature_index,
        project_root=project_root,
        iteration=0,
        max_retry=max_retry,
        status="idle",
        reflections=[],
        error_log=[],
        evaluation_score=0,
        evaluation_verdict="SKIP",
        evaluation_findings=[],
        pending_approval=False,
        pending_action={},
        session_id=session_id,
        last_good_commit="",
        metadata={},
    )

"""
main.py
───────
하네스 엔지니어링 실행 진입점

사용법:
  python main.py --task "로그인 폼 컴포넌트 구현" --project ./web_target
  python main.py --task "대시보드 페이지" --max-retry 3 --session my-session-01
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from harness.graph import build_harness_graph, visualize_graph
from harness.state import create_initial_state
from harness.memory import load_episodic_memory
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from harness.llm_errors import LLMUnavailableError
import config
import exit_codes


def run_harness(
    task: str,
    project_root: str,
    session_id: str | None = None,
    max_retry: int = 5,
    stream: bool = True,
    visualize: bool = False,
) -> dict:
    """
    하네스를 실행하고 최종 상태를 반환한다.

    Args:
        task:         구현할 기능 설명
        project_root: 프로젝트 루트 절대 경로
        session_id:   세션 ID (None이면 자동 생성)
        max_retry:    최대 Reflexion 반복 횟수
        stream:       스트리밍 모드 여부
        visualize:    그래프 시각화 저장 여부

    Returns:
        최종 HarnessState 딕셔너리
    """
    # 세션 ID 자동 생성
    if session_id is None:
        session_id = f"session-{uuid.uuid4().hex[:8]}"

    print(f"\n{'='*60}")
    print(f"🚀 하네스 엔지니어링 시작")
    print(f"   세션: {session_id}")
    print(f"   작업: {task}")
    print(f"   경로: {project_root}")
    print(f"   최대 재시도: {max_retry}회")
    print(f"{'='*60}\n")

    # 이전 에피소드 메모리 로드
    prev_reflections = load_episodic_memory(session_id, max_items=3)
    if prev_reflections:
        print(f"💭 이전 반성 메모 {len(prev_reflections)}개 로드됨")

    # 그래프 빌드
    # 체크포인터 설정 전달 (TS-007) — 이전에는 플래그를 넘기지 않아
    # config.USE_PERSISTENT_MEMORY / DATABASE_URL 이 죽은 설정이었다.
    app = build_harness_graph(
        max_retry=max_retry,
        use_persistent_memory=config.USE_PERSISTENT_MEMORY,
        db_uri=config.DATABASE_URL or None,
    )

    # 그래프 시각화 (선택)
    if visualize:
        visualize_graph(app, "harness_graph.png")

    # 초기 상태 설정
    initial_state = create_initial_state(
        task=task,
        project_root=str(Path(project_root).resolve()),
        session_id=session_id,
        max_retry=max_retry,
    )
    # 이전 반성이 있으면 초기 상태에 주입
    initial_state["reflections"] = prev_reflections
    initial_state["messages"] = [HumanMessage(content=task)]

    graph_config = {"configurable": {"thread_id": session_id}}
    final_state = initial_state

    try:
        if stream:
            # 스트리밍 실행 — 각 단계 실시간 출력
            for chunk in app.stream(initial_state, graph_config, stream_mode="values"):
                status    = chunk.get("status", "")
                iteration = chunk.get("iteration", 0)
                score     = chunk.get("evaluation_score", 0)
                verdict   = chunk.get("evaluation_verdict", "")

                status_icon = {
                    "reasoning":      "🤔",
                    "acting":         "⚡",
                    "reflecting":     "💭",
                    "evaluating":     "🔍",
                    "awaiting_human": "👤",
                    "escalated":      "🚨",
                    "done":           "✅",
                }.get(status, "⏳")

                print(f"{status_icon} [{status}] iter={iteration}"
                      + (f" score={score}" if score else "")
                      + (f" verdict={verdict}" if verdict else ""))

                final_state = chunk

                # Human-in-the-Loop 처리
                graph_state = app.get_state(graph_config)
                if graph_state.next == ("human_check",):
                    final_state = _handle_human_approval(app, graph_config, graph_state)

        else:
            # 단순 invoke 모드
            final_state = app.invoke(initial_state, graph_config)

    except KeyboardInterrupt:
        print("\n\n⚠️  사용자가 실행을 중단했습니다.")
        # 현재 상태 저장 (체크포인터가 자동 처리)

    except LLMUnavailableError as exc:
        # 인프라 장애 (쿼터/인증/백오프 소진) — 기능 실패가 아니다 (TS-005).
        # 트레이스백 대신 조치 가능한 보고서를 출력하고, metadata 에 마커를 남겨
        # exit_code_for_state() 가 전용 종료 코드로 변환하게 한다.
        _print_llm_unavailable(exc)
        final_state = {
            **final_state,
            "status": "failed",
            "metadata": {
                **(final_state.get("metadata") or {}),
                "llm_unavailable": {
                    "kind":     exc.kind,
                    "node":     exc.node,
                    "attempts": exc.attempts,
                    "fatal":    exc.fatal,
                },
            },
            "error_log": list(final_state.get("error_log") or []) + [exc.summary()],
        }

    # 결과 요약 출력
    _print_summary(final_state, session_id)
    return final_state


def _handle_human_approval(app, config, graph_state) -> dict:
    """Human-in-the-Loop 대화형 승인 처리."""
    pending = graph_state.values.get("pending_action", {})
    print("\n" + "="*60)
    print("👤 인간 승인 필요")
    print(f"   작업: {pending.get('type', '알 수 없음')}")
    print(f"   사유: {pending.get('reason', '')}")
    print("="*60)

    while True:
        answer = input("\n승인하시겠습니까? [yes/no/instruction]: ").strip().lower()
        if answer in ("yes", "y", "승인"):
            result = app.invoke(
                Command(resume={"approved": True}),
                config,
            )
            print("✅ 승인됨 — 실행 재개")
            return result
        elif answer in ("no", "n", "취소"):
            result = app.invoke(
                Command(resume={"approved": False, "instruction": "사용자가 취소"}),
                config,
            )
            print("❌ 취소됨")
            return result
        else:
            # 사용자 지시 전달
            result = app.invoke(
                Command(resume={"approved": True, "instruction": answer}),
                config,
            )
            print(f"✅ 지시 전달됨: '{answer}'")
            return result


def exit_code_for_status(status: str) -> int:
    """최종 status → 프로세스 종료 코드.

    0: done (정상 완료)
    1: escalated / cancelled (비정상이지만 인지된 종료)
    2: 그 외 (silent-abort 포함 — reasoning/acting 상태로 끝난 경우)
    3: LLM 공급자 사용 불가 — exit_code_for_state() 가 판정 (TS-005)
    """
    if status == "done":
        return exit_codes.OK
    if status in ("escalated", "cancelled"):
        return exit_codes.ESCALATED
    return exit_codes.NO_PROGRESS


def exit_code_for_state(state: dict) -> int:
    """최종 상태 → 종료 코드.

    인프라 장애(LLM 공급자 사용 불가)를 기능 실패와 구분해 3을 반환한다 (TS-005).
    night_shift.py 는 이 코드를 보고 attempt 를 소모하지 않고 런 전체를 중단한다.
    """
    if (state.get("metadata") or {}).get("llm_unavailable"):
        return exit_codes.LLM_UNAVAILABLE
    return exit_code_for_status(state.get("status", ""))


def _print_llm_unavailable(exc: LLMUnavailableError) -> None:
    """LLM 공급자 장애 보고서 — 트레이스백 대신 조치 가능한 정보를 출력한다."""
    bar = "=" * 60
    first = str(exc).splitlines()[0] if str(exc) else exc.kind
    print("")
    print(bar)
    print("[LLM 공급자 사용 불가] 기능 실패가 아닙니다 — 인프라 장애")
    print(bar)
    print(f"   분류:       {exc.kind}")
    print(f"   발생 노드:   {exc.node or '알 수 없음'}")
    print(f"   시도 횟수:   {exc.attempts}회")
    print(f"   원본 오류:   {first[:200]}")
    print(f"   조치:       {exc.advice()}")
    print(bar)


def _print_summary(state: dict, session_id: str) -> None:
    """실행 결과 요약을 출력한다."""
    print(f"\n{'='*60}")
    print(f"📊 실행 결과 요약 — 세션: {session_id}")
    print(f"{'='*60}")
    print(f"   최종 상태:    {state.get('status', '알 수 없음')}")
    print(f"   반복 횟수:    {state.get('iteration', 0)}회")
    print(f"   평가 점수:    {state.get('evaluation_score', 0)}/100")
    print(f"   평가 판정:    {state.get('evaluation_verdict', 'N/A')}")
    print(f"   반성 기록:    {len(state.get('reflections', []))}개")
    print(f"   오류 로그:    {len(state.get('error_log', []))}개")
    print(f"{'='*60}\n")


# ── CLI 인터페이스 ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="하네스 엔지니어링 실행기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py --task "로그인 폼 컴포넌트" --project ./web_target
  python main.py --task "대시보드" --max-retry 3 --no-stream
  python main.py --task "API 연동" --session my-session --visualize
        """
    )
    parser.add_argument(
        "--task",
        required=True,
        help="구현할 기능 설명",
    )
    parser.add_argument(
        "--project",
        default="./web_target",
        help="프로젝트 루트 경로 (기본: ./web_target)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="세션 ID (기본: 자동 생성)",
    )
    parser.add_argument(
        "--max-retry",
        type=int,
        default=config.MAX_RETRY,
        help=f"최대 Reflexion 반복 횟수 (기본: {config.MAX_RETRY})",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="스트리밍 모드 비활성화",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="그래프를 harness_graph.png로 저장",
    )

    args = parser.parse_args()

    # GOOGLE_API_KEY 확인
    import os
    from dotenv import load_dotenv
    load_dotenv()
    if not os.environ.get("GOOGLE_API_KEY"):
        print("❌ 오류: GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")
        print("   export GOOGLE_API_KEY=your_key_here")
        sys.exit(1)

    final_state = run_harness(
        task=args.task,
        project_root=args.project,
        session_id=args.session,
        max_retry=args.max_retry,
        stream=not args.no_stream,
        visualize=args.visualize,
    )

    code = exit_code_for_state(final_state)
    sys.exit(code)


if __name__ == "__main__":
    main()

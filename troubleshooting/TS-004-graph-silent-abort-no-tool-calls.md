---
id: TS-004
title: Coder가 도구 없이 텍스트만 응답하면 그래프가 조용히 종료되어 returncode=0으로 위장 성공
date: 2026-04-14
category: runtime
severity: high
status: resolved
component: harness/router.py
tags: [langgraph, react, gemini, silent-abort, exit-code]
---

## Symptoms
- `night_shift.py`에서 F-004 작업을 시도하면 `harness_runtime.log`가 매번
  `idle → reasoning → acting`까지만 찍고 즉시 요약 블록으로 진입.
- 요약: `iter=0`, `evaluation_score=0`, `verdict=SKIP`, `reflections=0`, `error_log=0`.
- `main.py`는 returncode 0 반환 → `night_shift.py`가 ✅ Success 출력.
- 그러나 `features.json`은 변경되지 않음. 3회 반복 후 같은 기능이 "⚠ Stuck"으로 마킹됨.

```
🤔 [reasoning] iter=0
⚡ [acting] iter=0
============================================================
📊 실행 결과 요약 — 세션: ...
   최종 상태:    acting
   반복 횟수:    0회
   평가 점수:    0/100
```

## Root cause
- `orchestrator → reason (coder_node)` 첫 턴에 Gemini가 **tool_calls 없이 순수 한국어 텍스트만** 반환.
- `route_after_reason` ([harness/router.py:37-67](../harness/router.py))가 "도구 호출 없음"을 "작업 완료"로 오인 → `__end__` 분기.
- 그래프가 정상 종료된 것처럼 보여 `app.stream()`이 자연 종료, `main.py`는 exit 0.
- 세 개의 결함이 한 증상으로 합쳐짐:
  - **D1 (router)**: `"no tool calls" ≠ "task complete"` 개념 혼동
  - **D2 (prompt/message)**: `coder_node`가 시스템 프롬프트를 `HumanMessage`로 감싸 Gemini에 전달 →
    연속된 Human 턴을 본 모델이 대화형 답변으로 응답 (tool 우선순위 하락)
  - **D3 (exit code)**: `main.py`가 terminal status(`done` vs silent `__end__`)를 구분하지 않음

## Fix
- [harness/router.py](../harness/router.py) — `route_after_reason`에서 `status=="acting" and iteration==0 and not reflections` 인 경우 `"no_progress_guard"` 반환. 이후 턴의 자연 종료는 기존처럼 `__end__`.
- [harness/graph.py](../harness/graph.py) — `no_progress_guard_node` 노드 신설. `error_log`에 `"[silent-abort] coder returned no tool calls on first turn"` 기록 후 `reflect`로 연결.
- [harness/nodes/agents.py](../harness/nodes/agents.py) — `coder_node`:
  - `[HumanMessage(content=system)]` → `[SystemMessage(content=system)]` (Gemini `system_instruction` 매핑)
  - `reflections` 있거나 이전 `error_log`에 `[silent-abort]` 마커 있을 때 `_TOOL_CALL_NUDGE` HumanMessage 주입
    ("다음 응답에서 반드시 하나 이상의 도구를 호출하십시오. `read_features` 또는 `list_directory` 부터 시작하십시오.")
- [main.py](../main.py) — `exit_code_for_status()` 신설. `run_harness` 반환값의 `status`를 바탕으로
  `done→0`, `escalated|cancelled→1`, 그 외(silent-abort 포함)→2로 매핑해 `sys.exit(code)`.

## Verification
- **재현**: 도구 없이 텍스트만 응답하도록 LLM을 스텁해 1회 실행 →
  `reason → no_progress_guard → reflect → reason` 경로 진입 확인. `error_log[0]`에 `[silent-abort]` 포함.
  `iteration`이 1로 증가. `max_retry` 초과 시 `escalate`로 라우팅 → `main.py` exit 1.
- **Happy path**: `SystemMessage` 기반 프롬프트로 정상 실행 시 첫 턴에 `read_features` 등 도구 호출 발생 →
  `act → evaluate → done` 진행. PASS면 `session_done_node`가 `gemini-progress.txt` 기록 + git commit,
  `main.py` exit 0, `night_shift.py` ✅ Success, `features.json`의 해당 기능 `passes: true`.
- **Regression**: `status="done"`, `"escalated"`, `"cancelled"` 경로는 `no_progress_guard`를 경유하지 않음
  (가드 조건 `iteration==0 and not reflections and status=="acting"`로 좁게 제한됨).
- 모든 수정 파일 `ast.parse` 통과 확인.

## Prevention
- 라우터에서 "빈 AIMessage == 완료"로 단정하지 말 것. 반드시 `status`, `iteration`, `reflections`를 함께 확인.
- Gemini에 시스템 지시는 `SystemMessage`로 전달 (langchain-google-genai가 `system_instruction`에 매핑).
  `HumanMessage`로 래핑하면 연속 Human 턴이 되어 tool 호출 우선순위가 떨어짐.
- `main.py`는 terminal status를 exit code에 반영할 것. 그래프의 조용한 종료가 ✅ Success로 위장되지 않도록.
- 첫 turn이 도구 호출 없이 끝나면 **재시도 가능한 실패**로 취급 (Reflexion 루프 유입).

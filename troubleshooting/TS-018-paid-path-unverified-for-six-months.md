---
id: TS-018
title: 유료 경로가 6개월간 검증 없이 방치됐다 — 스모크 테스트가 즉시 버그 2건을 찾아냈다
date: 2026-10-02
category: testing
severity: high
status: resolved
component: harness/router.py, harness/nodes/agents.py, repro_ts018.py
tags: [coverage, dead-code, reflexion, smoke-test, i18n, observability]
guard: repro_ts018 이 LLM 을 스텁으로 바꿔 그래프를 끝까지 돌린다 (토큰 0)
exposure: paid-path-smoke
resolution: use
---

## Symptoms
사용자가 물었다 — *"이건 실제 의미있는 코드들이 맞을까? langchain을 실제 사용하는거야?"*

주장 대신 측정했다. 커버리지에서 `import`·`def`·모듈 상수를 제외하고
**함수 본문이 실행된 줄**만 셌다.

| 모듈 | 전체 | 실제 로직 실행 |
|---|---|---|
| `harness/nodes/agents.py` | 125 | **1** (상수 하나) |
| `harness/router.py` | 94 | **1** |
| `harness/graph.py` | 74 | **1** |
| `harness/memory.py` | 66 | **1** |
| `harness/tools.py` | 205 | 12 |
| `main.py` | 130 | 9 (종료 코드 매핑만) |

**359 statements 중 실행되는 로직 4줄.** langchain 은 진짜 API 사용이었고
(`StateGraph`·`ToolNode`·`@tool`·`add_messages`·`interrupt/Command`),
실제로 돌았던 증거도 있었다 — `.harness_memory/` 의 Reflexion 산출물 67개,
timestamp `2026-04-14`. TS-004/005/007 은 돌려봐야만 발견되는 실패였다.

그런데 **그 뒤로 한 번도 안 돌았다.** 그 상태에서 TS-017 이
`verify.py`·`tags.py`·`mutate.py` 를 리팩터했다. `tools.py` 는 `verify.apply_flag` 를
호출하는데 아무것도 그 연결을 검사하지 않았다. 수동으로 확인하니 살아 있었지만
**그것은 검증이 아니라 운이었다** — TS-015(모드 전환 후 측정이 고아가 된 것을 몰랐다)와
같은 구조다.

## Root cause
유료 경로는 LLM 이 있어야 돌아간다고 **전제**했다. 그래서 테스트를 아예 쓰지 않았다.
그 전제가 틀렸다. 모든 에이전트 노드가
`_get_llm()` → `bind_tools()` → `invoke_llm(.., node=...)` 를 거치고,
`invoke_llm` 이 **노드 이름을 인자로 받는다.** 즉 노드별 응답을 주입할 지점이
처음부터 있었다 — 토큰 없이 그래프를 끝까지 돌릴 수 있었다.

## Fix — 스모크 테스트 + 그것이 찾아낸 버그 2건
### `repro_ts018.py` (78 검증)
LLM 을 스텁으로 바꿔 실제 LangGraph 그래프를 돌린다. 토큰 0, API 키 불필요.
`ChatGoogleGenerativeAI` 는 **생성 즉시 터지는 센티넬**로 교체해 네트워크 호출 0회를
구조적으로 보장한다 (`.env` 가 로드되므로 키 부재로는 증명할 수 없다).

### 버그 1 — 도구 실패가 라우터에 보이지 않았다
`harness/tools.py` 의 도구들은 실패를 **예외로 올리지 않고 문자열로 반환**한다.
그 문자열은 전부 한국어다 — `[오류] 파일을 찾을 수 없습니다`, `[보안 오류] …`.

`route_after_act` 의 감지 정규식은 영어만 봤다:
```python
re.search(r"\b(Error|Exception|Traceback|FAIL(?:ED)?)\b", content, re.I)
```

실측: **도구 오류 반환 16건 중 영어 키워드를 포함한 것 0건.**
따라서 라우터는 `status == "error"`(예외를 올린 경우)만 잡고 **반환된 실패는 전부 놓쳤다.**
도구가 실패해도 `continue` 로 분기해 reason 으로 돌아갔고,
`MAX_TOOL_CALLS_PER_FEATURE`(15)에 걸릴 때까지 돌다 `evaluate` 로 갔다.
**도구 실패에 대해 Reflexion 루프가 한 번도 작동하지 않았다.**

수정: `router.TOOL_FAILURE_RE` 로 패턴을 상수화하고 한국어 마커를 추가했다.
`[거부]` 는 **일부러 제외**했다 — 증거 게이트의 거부는 장애가 아니라 **판정**이고
(TS-006/TS-008), 거부를 오류로 취급하면 정상적인 게이트 작동마다 Reflexion 이 돌아
재시도 예산(`max_retry`)을 소모한다.

### 버그 2 — Reflector 가 오류를 보지 못한 채 반성했다
버그 1을 고치자 `reflect` 가 작동했다. 그런데 Reflector 의 프롬프트를 들여다보니
`<error_log>직접적인 오류 로그 없음</error_log>` 이 들어가 있었다.

원인 사슬:
- `route_after_act` 는 실패를 감지하지만 **라우터이므로 상태를 쓰지 않는다**
- `coder_node` 의 오류 스캔은 **LLM 응답 본문**만 보고, 그것은 `act` **이전**이다
- `reflector_node` 는 `state["error_log"]` 만 읽는다
- 따라서 도구가 실패해서 Reflexion 이 돌았는데 **신호가 비어 있었다**

이것이 보관된 F-004 증거
(`troubleshooting/evidence/F-004-reflexion-confabulation/` —
"정보 없는 오류 신호에서 Reflexion 이 작화한다")의 **기계적 원인**이다.
신호가 모호했던 게 아니라 **아예 없었다.**

수정: `agents._tool_failures_from()` 을 추가해, `error_log` 가 비어 있으면
최근 메시지에서 실패한 ToolMessage 를 직접 뽑아 프롬프트에 넣는다.
판정 기준은 `router.TOOL_FAILURE_RE` 를 **공유**한다 — 라우터가 "reflect 로 보낸다"고
판단한 것과 Reflector 가 "이게 실패다"라고 읽는 것이 어긋나면 다시 신호 없는 반성이 된다.

## 스모크 테스트를 쓰면서 걸린 함정 (내 쪽 오류)
처음 4건이 실패했는데 **전부 내 가정이 틀린 것**이었다. 기록해 둔다 —
같은 착오를 다시 하기 쉽다.

1. **`interrupt()` 가 아니라 `interrupt_before` 로 멈춘다.** `compile(interrupt_before=["human_check"])`
   이므로 노드 **진입 전**에 정지한다. 따라서 `invoke()` 반환값의 `__interrupt__` 가 아니라
   `app.get_state(cfg).next == ("human_check",)` 로 확인해야 한다 — `main.py` 도 그렇게 한다.
2. **`error_log` 는 Reflector 가 의도적으로 비운다.** `state.keep_last_n` 의 `RESET_SENTINEL`
   규약이다. 최종 상태만 보면 silent-abort 마커가 사라져 있다. 중간 상태
   (`stream(stream_mode="values")`)를 보관해야 '언젠가 설정됐다'를 검증할 수 있다.
3. **`write_progress` 는 추가(append)한다.** 덮어쓰기를 가정하면 틀린다.
4. **같은 `AIMessage` 인스턴스를 두 번 넣으면 두 번째가 사라진다.** `add_messages` 리듀서가
   메시지 `id` 로 중복을 제거해 *갱신*으로 처리한다. 그러면 `messages[-1]` 이 ToolMessage 로
   남아 `route_after_reason` 이 `act` 대신 `evaluate` 로 보낸다. 대본의 각 항목은
   **매번 새로 생성**해야 한다.

## Verification
`repro_ts018.py` — **78/78 PASS**. 네트워크·API 키·실제 jest 없음.

- 그래프 조립 11건 — 노드 10종 + 체크포인터 존재
- 전체 성공 사이클 11건 — 노드 호출 순서, 실제 도구 실행(진짜 파일 읽기),
  도구 계층별 바인딩(orchestrator 에 `write_file` 없음), 핸드오프 append, 종료 코드
- **리팩터된 게이트 도달 8건** ← TS-017 의 맹점. 태그 없으면 거부/플래그 불변,
  태그+커버리지면 반영/`verification`·`evidence_sources` 기록
- silent-abort 9건 — 중간 상태의 마커, RESET_SENTINEL 초기화, 디스크 반성 기록
- IRREVERSIBLE 11건 — `get_state().next`, `interrupt_before` 설정,
  `act` 미실행, `Command(resume={"approved": False})` → cancelled
- LLM 장애 6건 — 트레이스백 없이 metadata 마커, 종료 코드 3, FATAL_INFRA 분류
- **도구 실패 감지 8건** ← 버그 1. 한국어/영어 양방향, `[거부]` 제외, 도구 반환값 실측
- escalate 5건
- **Reflector 신호 7건** ← 버그 2. 프롬프트에 실제 `[오류]` 와 도구 이름이 담기는지,
  성공 ToolMessage 는 제외하는지
- 스텁 누출 4건 — 센티넬 생성 0회

**커버리지 재측정 — 맹점이 사라졌다** (실제 로직 실행 줄):

| 모듈 | 전 | 후 |
|---|---|---|
| `nodes/agents.py` | 1 (1%) | **97 (70%)** |
| `router.py` | 1 (1%) | **59 (62%)** |
| `graph.py` | 1 (1%) | **33 (45%)** |
| `main.py` | 9 (7%) | **54 (42%)** |
| `state.py` | — | **100%** |
| `memory.py` | 1 (2%) | 12 (18%) |
| `tools.py` | 12 (6%) | 31 (15%) |

전체 61% → **71%**. 하네스 회귀 **404건** 전부 통과 (기존 326 + TS-018 78).

## Prevention
- **"LLM 이 있어야 돌아간다"를 의심할 것.** 호출 지점이 한 군데로 모여 있으면
  스텁으로 전부 돌릴 수 있다. 이 그래프는 처음부터 그랬다 — 6개월을 놓쳤다.
- **커버리지는 `import` 줄을 세어 15~30% 를 만들어낸다.** 모듈이 import 되기만 해도
  그 숫자가 나온다. `def`·상수·import 를 제외한 **본문 실행 줄**을 따로 세야
  "돌지 않는다"가 드러난다.
- **오류 문자열의 언어를 맞출 것.** 도구가 한국어로 실패를 알리고 라우터가 영어로
  찾으면 아무도 눈치채지 못한다. 실패 판정 패턴은 **상수로 한 곳에** 두고,
  그것을 읽는 쪽과 쓰는 쪽이 **같은 상수를 공유**하게 한다.
- **실패를 감지한 곳과 기록하는 곳을 분리하지 말 것.** 라우터는 상태를 못 쓰므로,
  감지만 하고 아무도 기록하지 않으면 다음 노드가 신호 없이 일한다.
  "왜 이 노드로 왔는가"가 상태에 남아야 한다 (TS-009 와 같은 교훈).
- **검증 없는 코드를 그대로 리팩터하지 말 것.** 리팩터가 끝난 뒤 "수동으로 확인했다"는
  영구적 보증이 아니다. 다음 리팩터는 확인하지 않는다.
- **테스트가 처음 실패하면 코드가 아니라 테스트의 가정부터 의심할 것.**
  이번에 처음 실패한 4건은 전부 내 가정 오류였고, 그 다음 2건이 진짜 버그였다.
  가정을 먼저 치우지 않으면 진짜 버그가 노이즈에 묻힌다.

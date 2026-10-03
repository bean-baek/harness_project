---
id: TS-005
title: LLM 쿼터 초과(429)가 트레이스백으로 터지며 night_shift가 멀쩡한 기능들을 stuck으로 마킹
date: 2026-10-01
category: runtime
severity: high
status: resolved
component: harness/llm_errors.py
tags: [gemini, quota, rate-limit, resilience, exit-code, night-shift]
guard: `llm_errors.py` 가 쿼터/인증 오류를 런 중단으로 분류한다 (attempt 미소모)
exposure: paid-path-quota
resolution: use
---

## Symptoms
- `night_shift.py` 실행 중 모든 작업이 **7초 만에** 실패하며 raw 트레이스백 출력:
  ```
  langchain_google_genai.chat_models.ChatGoogleGenerativeAIError:
    Error calling model 'gemini-2.5-pro' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED.
    {'error': {'code': 429, 'message': 'Your project has exceeded its monthly spending cap. ...'}}
  ```
- `harness_runtime.log` 타임라인 — F-004 attempt 3 (21:47:37) → F-005 attempt 1 (21:47:44)
  → F-005 attempt 2 (21:47:51). 기능당 3회씩 소모되며 **남은 71개 기능까지 전부
  `⚠ Stuck` 으로 마킹되는 경로**로 진입.
- 진짜 원인(결제 한도 초과)은 70줄 트레이스백 안에 묻혀 있고, 운영자에게 보이는 결론은
  "F-004~F-075 기능 구현 실패"라는 **완전히 잘못된 신호**.
- 반성 메모리도 오염됨: `reflection_001.json` 은
  "에이전트의 파일 수정 도구 자체가 작동하지 않는다"(confidence 5%)라고 결론 —
  LLM 호출이 아예 성공하지 못한 런을 기능 실패로 해석한 결과.
  → 해당 반성 4건은 주입 경로에서 분리해
  [evidence/F-004-reflexion-confabulation/](evidence/F-004-reflexion-confabulation/) 로 보존했다
  (오진이므로 재주입은 해롭지만, 'Reflexion 이 오류 신호 부재 시 날조한다'는 1차 증거다).

## Root cause
세 개의 결함이 한 증상으로 합쳐짐:

- **D1 (예외 처리 부재)**: `harness/nodes/agents.py` 의 5개 노드가
  `llm.invoke()` / `llm_with_tools.invoke()` 를 맨손으로 호출. 공급자 예외가
  LangGraph → `app.stream()` → `main.py` 를 그대로 관통해 프로세스를 죽였다.
  `_get_llm(max_retries=2)` 는 langchain 내부 재시도일 뿐, **쿼터 초과처럼
  재시도가 무의미한 오류와 분당 한도처럼 재시도가 유효한 오류를 구분하지 못한다.**
- **D2 (종료 코드 의미 혼동)**: 트레이스백으로 죽은 프로세스는 exit 1 —
  TS-004에서 정의한 `escalated`(인지된 기능 실패)와 같은 코드.
  `night_shift.py` 는 "인프라 장애"를 표현할 코드 자체를 갖고 있지 않았다.
- **D3 (실패 귀속 오류)**: `night_shift.main()` 이 **모든** 비정상 종료에
  `attempts[feat_id]` 를 소모. 원인이 기능과 무관한 전역 장애여도
  3회 소모 후 `stuck` 마킹하고 다음 기능으로 넘어가 같은 장애를 다시 맞는다.
  → 장애 1건이 features.json 전체를 오염시키는 증폭 구조.

## Fix
- **[harness/llm_errors.py](../harness/llm_errors.py) (신설)**
  - `classify_llm_error(exc) -> (kind, retry_after)` — 타입이 아닌 **코드/메시지**로 판정
    (langchain이 `google.genai.errors.ClientError` 를 `ChatGoogleGenerativeAIError` 로 감싸므로).
    - `quota_exhausted` / `auth` → **fatal**, 재시도 무의미
    - `rate_limited` / `transient` → 지수 백오프 재시도 (공급자가 준 `retryDelay` 우선)
    - `unknown` → **원본 예외 그대로 전파** (하네스 버그를 인프라 장애로 위장하지 않는다)
  - 분류 우선순위 주의: 무료 티어 **분당** 한도 메시지에도
    `"please check your plan and billing details"` 보일러플레이트가 섞여 나온다.
    따라서 ① 지출 캡/일일 쿼터(강한 신호) → ② 분당 마커 또는 `retryDelay` 존재 → ③ 결제 문구(약한 신호)
    순으로 판정한다. `"...FreeTier"` 라벨 자체는 하드 신호가 아니다.
  - `invoke_llm(llm, messages, node=...)` — 모든 노드의 LLM 호출 단일 진입점.
    fatal 또는 재시도 소진 시 `LLMUnavailableError` (kind / node / attempts / retry_after / advice 포함).
- **[harness/nodes/agents.py](../harness/nodes/agents.py)** — 5개 호출 지점
  (`orchestrator` / `initializer` / `reason(coder)` / `evaluate` / `reflect`) 전부
  `invoke_llm(..., node="<이름>")` 경유. raw `.invoke()` 잔존 0건.
- **[exit_codes.py](../exit_codes.py) (신설)** — `main.py` ↔ `night_shift.py` 공유 종료 코드 규약.
  stdlib only (night_shift가 langgraph 임포트 없이 읽는다).
  `OK=0`, `ESCALATED=1`, `NO_PROGRESS=2`, **`LLM_UNAVAILABLE=3`**, `FATAL_INFRA={3}`.
- **[main.py](../main.py)** — `except LLMUnavailableError` 추가:
  트레이스백 대신 조치 가능한 보고서 출력 + `metadata.llm_unavailable` 마커 기록.
  `exit_code_for_state(state)` 신설 — 마커가 있으면 3, 없으면 기존 `exit_code_for_status()` 위임
  (TS-004의 status→코드 매핑은 그대로 보존).
- **[night_shift.py](../night_shift.py)** — `returncode in exit_codes.FATAL_INFRA` 이면
  **attempt 를 되돌리고(`attempts[feat_id] -= 1`) 런 전체를 즉시 중단.**
  features.json 의 `passes=false` 는 그대로 보존 → 한도 해제 후 재실행하면 이어서 진행.
- **[config.py](../config.py)** — `LLM_MAX_ATTEMPTS`(4) / `LLM_BACKOFF_BASE_SEC`(5) /
  `LLM_BACKOFF_MAX_SEC`(60), 환경변수 `HARNESS_LLM_MAX_ATTEMPTS` 등으로 조정.

### 왜 그래프 안(escalate 노드)에서 처리하지 않는가
쿼터 초과는 **기능과 무관한 전역 장애**다. Reflexion 루프에 태우면 반성 메모리가
"파일 도구가 없다" 같은 허위 근본 원인으로 오염되고(실제로 발생함),
`InMemorySaver` 체크포인터로는 프로세스 재개도 불가능하다. 따라서 그래프를 빠져나와
**프로세스 경계에서 중단**하고, 재실행 시 features.json 기준으로 이어가게 하는 것이 맞다.

## Verification
`repro_ts005.py` — LLM 전부 스텁, 실제 API 호출 없음. **37/37 PASS**.

- **분류 (11건)**: 월 지출 캡 → `quota_exhausted` / 분당 한도 → `rate_limited` + `retryDelay` 27s 파싱 /
  일일 쿼터 → `quota_exhausted` / 잘못된 API 키 → `auth` / 503 → `transient` /
  무료 티어 분당 한도(결제 보일러플레이트 포함) → `rate_limited` /
  `ValueError("tool schema invalid")` → `unknown`.
- **재시도 정책**: 쿼터 초과는 **호출 1회로 중단, sleep 0회**.
  일시 오류는 백오프 2회 후 3번째 시도 성공(첫 대기 = `retryDelay` 27s 우선 적용).
  `max_attempts` 소진 시 `rate_limited`(non-fatal)로 보고. `unknown` 은 원본 `ValueError` 전파.
- **종료 코드**: `done→0`, `escalated→1`, `acting(silent-abort)→2`, `llm_unavailable→3`.
  TS-004 회귀: `exit_code_for_status("done"/"cancelled"/"reasoning") == (0,1,2)` 불변.
- **night_shift**: 인프라 장애 주입 시 **기능 1개만 시도하고 종료 코드 3으로 중단**,
  attempt 미소모, stuck 마킹 0건.
  대조군(기능 실패 코드 2)은 기존대로 3개 기능 × 3회 = 9회 시도 후 stuck 3건, 종료 코드 1.
- **실 환경 E2E**: 한도가 걸린 실제 키로 `python main.py --task ... --session ts005-verify` 실행 →
  트레이스백 0줄, `[LLM 공급자 사용 불가]` 보고서(분류 `quota_exhausted`, 노드 `orchestrator`,
  조치 안내) 출력, **exit code 3** 확인.

## Prevention
- LLM 호출은 반드시 `harness.llm_errors.invoke_llm()` 경유 — 새 노드 추가 시 raw `.invoke()` 금지.
  (점검: `grep -n "\.invoke(" harness/nodes/agents.py` 에 LLM 호출이 남지 않아야 한다.)
- **"프로세스가 죽었다" ≠ "기능이 실패했다"**. 자동 재시도 루프는 실패를 귀속시킬 대상을
  반드시 종료 코드로 구분할 것. 전역 장애에 attempt 를 소모하면 장애 1건이 백로그 전체를 오염시킨다.
- 공급자 오류 메시지는 타입이 아닌 **코드 + 메시지 패턴**으로 분류하고,
  분류 불가(`unknown`)는 삼키지 말고 전파할 것 — 하네스 버그가 인프라 장애로 위장된다.
- 한도 초과 시 저비용 모델로 계속하려면 `HARNESS_LLM_MODEL=gemini-2.5-flash` 로 재실행.

# 하네스 엔지니어링 (Harness Engineering)

> **자율 코딩 에이전트를 "돌리는 법"이 아니라 "운영하는 법"을 만드는 프로젝트.**

LLM 에이전트에게 코드를 쓰게 하는 것은 쉽다. 어려운 것은 **사람이 보지 않는 동안
에이전트가 만든 결과를 신뢰할 수 있게 만드는 것**이다. 이 저장소는 그 신뢰를 만드는
장치(harness)를 구현하고, 그 장치가 깨지는 방식을 전부 기록한다.

---

## 1. 결과물이 무엇이고 무엇이 아닌가

| | |
|---|---|
| **결과물이다** | `harness/` — 에이전트 실행·검증·측정·중단을 관리하는 운영 계층 |
| **결과물이다** | `troubleshooting/` — 실제로 터진 실패 모드 **14건**의 재현·원인·수정·검증 기록 |
| **결과물이 아니다** | `web_target/` — 투두 앱. 하네스를 시험하기 위한 **피험체**이자 벤치마크 과제 |

`web_target` 의 기능 75개(`features.json`)는 목표가 아니라 **측정 수단**이다.
피험체의 결함은 **"이 실패가 하네스에 교훈을 주는가"** 로 가려 선택적으로만 고친다 (§8).

### 설계 원칙 — 다섯 가지 불신

1. **자기 보고를 믿지 않는다.** "구현했다"는 증거가 아니다. 완료 플래그는 도구가
   테스트를 실행해 입증한 뒤에만 기록된다 (TS-006).
2. **스위트 녹색을 믿지 않는다.** 전체 테스트 통과도 **그 기능의** 증거가 아니다.
   해당 기능 ID 를 인용하는 통과 테스트를 요구한다 (TS-008).
3. **단위 테스트를 믿지 않는다.** 테스트가 검증 대상의 구조를 공급하면 그 구조는
   검증되지 않는다. F-005 는 게이트를 통과했지만 앱에 해당 라우트가 없었다 (TS-013).
4. **실패의 원인을 과제에 전가하지 않는다.** 쿼터 초과·인증 실패는 기능의 잘못이 아니므로
   attempt 를 소모하지 않고 런 전체를 중단한다 (TS-005).
5. **비가역 행위는 사람이 승인한다.** 도구는 3계층 권한을 갖고, `IRREVERSIBLE` 은
   그래프를 멈춰 승인을 기다린다.

---

## 2. 두 가지 실행 모드

| | 토큰 없는 모드 (권장) | 유료 API 모드 |
|---|---|---|
| 추론 엔진 | **Claude Code 세션** (구독 비용에 포함) | Gemini API (종량 과금) |
| 강제 | `python -m harness.cli` (결정론적) | 동일한 게이트 + LangGraph 라우터 |
| 무인 실행 | 불가 — 사람이 세션을 열어야 한다 | **가능** (`night_shift.py`, 30분 타임아웃) |
| 의존성 | 표준 라이브러리 + jest | langchain, langgraph, API 키 |

**왜 분리했는가**: 코드를 성격별로 세어보니 결정론적 기계(게이트·측정·태그 린터·도구·CLI)
**2,703줄**은 토큰을 전혀 쓰지 않고, **2,357줄**만이 유료 API를 돌리기 위해 존재한다.
**가치 있는 쪽은 이미 무료였다** (TS-010 — 당시 측정은 2,060줄, 이후 측정·린터 추가로 늘었다).

**왜 전부 마크다운으로 가지 않는가**: 마크다운은 **권고만** 할 수 있다.
"테스트를 먼저 실행하십시오"가 docstring 권고였을 때 에이전트는 무시하고 자가 채점했고,
판별력 측정 결과 **75개 기능 중 어느 것이든** 통과로 기록할 수 있는 상태였다.
그래서 **절차는 문서에, 판정은 코드에** 둔다.

---

## 3. 설치

```bash
pip install -r requirements.txt          # 하네스 (유료 모드용. 토큰 없는 모드는 표준 라이브러리만 필요)
cd web_target && npm install && cd ..    # 대상 앱
# 유료 모드만: .env 에 GOOGLE_API_KEY=... (절대 커밋 금지 — .gitignore 등록됨)

bash scripts/init.sh --install           # 위 전부를 한 번에
```

---

## 4. 토큰 없는 모드 사용법

```bash
python -m harness.cli next           # 다음 미구현 기능 명세 + 태그 규약
python -m harness.cli show F-006     # 특정 기능 명세와 기록된 증거
python -m harness.cli verify F-006   # 게이트 판정만 (플래그 변경 없음)
python -m harness.cli mark F-006     # 게이트 통과 시에만 기록  (0 통과 / 1 거부 / 2 입력오류)
python -m harness.cli unmark F-006   # 미완성으로 되돌림 (증거 제거)
python -m harness.cli audit          # 통과 플래그 전수 재검증
python -m harness.cli tags           # 태그가 옳은 기능을 가리키는지 검사
python -m harness.cli report         # 판별력 + 실행 로그 측정
```

Claude Code 세션에서는 [.claude/skills/harness/SKILL.md](.claude/skills/harness/SKILL.md) 가
절차를 안내한다 — 네 가지 불신 → 구현 → 태그 테스트 → 게이트 → 자기평가 → 기록.
`--project` 는 서브명령 앞뒤 어디에 써도 된다.

### 4.1 완료 플래그는 증거가 있어야 기록된다

`mark` 는 **도구가 직접 전체 스위트를 실행**하고, 두 조건을 모두 만족할 때만 플래그를 쓴다.

1. 스위트에 실패 테스트 0건 — 다른 기능을 깨뜨리지 않았다
2. **해당 기능 ID 를 이름에 포함한 통과 테스트가 1개 이상**

**태그 규약** — 새로 만든 규칙이 아니라 `LoginForm.test.tsx` 가 이미 쓰던 관행이다:

```ts
describe('F-005: 인증되지 않은 사용자가 보호된 페이지 접근 시 리다이렉트', ...)  // 기능 태그
test('F-005.3: 원래 URL 이 ?redirect= 로 보존된다', ...)                      // 단계 태그
```

통과 시 **무엇을 근거로 통과시켰는지**가 `features.json` 에 함께 기록된다:

```json
"verification": {
  "verified_at": "2026-10-02T...", "verified_by": "update_features/jest",
  "level": "feature", "suite": { "total": 51, "passed": 51, "failed": 0 },
  "summary": "suite 51/51 passed | tagged 24 passed | steps 3/3 covered",
  "evidence_tests": ["F-005: ... F-005.3: 원래 URL 이 ?redirect= 로 보존된다", "..."],
  "steps_covered": [1, 2, 3]
}
```

- 테스트 경로는 **도구가 `"."` 로 고정** — 쉬운 테스트만 골라 통과를 조작할 수 없다.
- 엄격도: `HARNESS_EVIDENCE_LEVEL` = `suite` / `feature`(기본) / `step`.
  단계 커버리지는 어느 수준이든 **측정해 기록**한다.
- 끄는 방법은 운영자에게만 있다: `HARNESS_REQUIRE_TEST_EVIDENCE=false` (디버깅 전용).

---

## 5. 유료 API 모드

```bash
python main.py --task "기능 설명" --project ./web_target   # 기능 하나
python night_shift.py                                      # 무인 연속 실행
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--task` | (필수) | 구현할 기능 설명 |
| `--project` | `./web_target` | 대상 프로젝트 루트 |
| `--session` | 자동 생성 | 같은 ID 를 쓰면 이전 반성 메모리를 이어받는다 |
| `--max-retry` | 5 | Reflexion 반복 상한 |
| `--no-stream` / `--visualize` | off | 스트리밍 비활성화 / 그래프 PNG 저장 |

### 5.1 그래프

```
START ─┬─(최초)─→ initializer ─┐
       └─(이후)─→ orchestrator ─┤
                                ↓
                    ┌───────→ reason (Coder: ReAct Thought)
                    │           ↓ 도구 호출?
                    │     ┌─────┴──────┬──────────────┐
                    │     ↓            ↓              ↓
                    │   act        human_check   no_progress_guard
                    │ (ToolNode)  (IRREVERSIBLE)  (도구 호출 없음)
                    │     ↓                           ↓
                    └─────┤                        reflect ←───┐
                          ↓                           ↑        │
                      evaluate (Evaluator: 증거 채점) ─┘        │
                          ↓                                    │
                    PASS? ─┬─ yes → done (핸드오프 + 커밋)      │
                           └─ no  → reflect (Reflexion) ───────┘
                                      ↓ max_retry 초과
                                   escalate
```

| 에이전트 | 역할 |
|---|---|
| P-01 Orchestrator | 다음 작업 선택, 위임 |
| P-02 Initializer | 최초 1회 환경 구성 |
| P-03 Coder | ReAct 루프로 실제 구현 |
| P-04 Evaluator | **도구 실행 기록만 보고** 채점 (기능40/품질30/성능20/보안10, 75점 합격) |
| P-05 Reflector | 5-Why 반성 → 에피소드 메모리 |

**도구 권한 3계층** (`harness/tools.py`, 15종)

| 계층 | 도구 | 정책 |
|---|---|---|
| `READ_ONLY` | `read_file`, `list_directory`, `read_features`, `read_progress`, `list_troubles`, `read_trouble` | 승인 불필요 |
| `STATEFUL` | `write_file`, `run_tests`, `bash_command`, `git_commit`, `update_features`, `write_progress`, `log_trouble` | 감사 로그 |
| `IRREVERSIBLE` | `deploy_prod`, `delete_resource` | **라우터가 `human_check` 로 강제 분기** |

### 5.2 종료 코드 — 실패의 책임 소재를 구분한다

| 코드 | 의미 | `night_shift` 의 반응 |
|---|---|---|
| 0 | `done` | 다음 기능으로 |
| 1 | `escalated` / `cancelled` | attempt 소모, 3회 초과 시 stuck |
| 2 | 그 외 (silent-abort 포함) | attempt 소모 |
| **3** | **LLM 공급자 사용 불가 (인프라)** | **attempt 미소모 + 런 전체 즉시 중단** |

코드 3 은 쿼터 초과·인증 실패·백오프 소진이다. `features.json` 은 보존되고,
원인을 해결한 뒤 재실행하면 이어서 진행한다. 종료 상태는 `night_shift` 가
`finally` 에서 **항상** `[END] exit= outcome= elapsed_sec=` 로 기록한다 (TS-009).

---

## 6. 하네스 자체를 측정한다

```bash
python -m harness.cli report
```

**판별력 원칙** — 모든 입력을 통과시키는 기준은 기준이 아니다. 증거 수준별로 전체 기능을
판정해 통과율을 센다. LLM 호출이 없어 API 쿼터와 무관하게 재현된다.

| 증거 수준 | 통과 | 통과율 |
|---|---|---|
| `suite` (TS-006 동작) | 75 / 75 | **100.0%** |
| `feature` (기본) | 6 / 75 | 8.0% |
| `step` (최고 엄격도) | 2 / 75 | 2.7% |

**판별력 92%** — `suite` 기준이 통과시킨 것 중 대부분은 근거 없는 통과였다.
이 수치는 "게이트가 옳다"는 증명이 아니라 **"게이트를 끈 것과 비교해 실제로 다른 일을
한다"는 반증 가능한 측정**이다. *(저자 측정, 독립 검증 필요)*

근거와 방법론: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)

---

## 7. 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `GOOGLE_API_KEY` | (없음) | 유료 모드 필수 |
| `HARNESS_LLM_MODEL` | `gemini-2.5-pro` | 한도 초과 시 `gemini-2.5-flash` 로 계속 가능 |
| `HARNESS_LLM_MAX_ATTEMPTS` | 4 | 일시 오류 재시도 (쿼터 초과는 재시도 안 함) |
| `HARNESS_LLM_BACKOFF_BASE` / `_MAX` | 5 / 60 | 백오프 초 |
| `HARNESS_MAX_RETRY` | 5 | Reflexion 반복 상한 |
| `HARNESS_EVAL_THRESHOLD` | 75 | Evaluator 합격선 |
| `HARNESS_REQUIRE_TEST_EVIDENCE` | `true` | 증거 게이트 (운영자 전용 차단 해제) |
| `HARNESS_EVIDENCE_LEVEL` | `feature` | `suite` / `feature` / `step` |
| `HARNESS_PERSISTENT` / `DATABASE_URL` | `false` / (없음) | 체크포인터 영속화 (아래 주의) |
| `HARNESS_MEMORY_DIR` | `./.harness_memory` | 에피소드 메모리 경로 |
| `DEV_PORT` / `API_PORT` | 5173 / 3001 | 개발 서버 포트 |

> **영속화 주의**: `langgraph-checkpoint-postgres` 미설치 시 `HARNESS_PERSISTENT=true` 여도
> 경고와 함께 `InMemorySaver` 로 폴백한다(프로세스 간 재개 불가).
> 활성화: `pip install langgraph-checkpoint-postgres psycopg[binary]` (TS-007)

---

## 8. 피험체 결함 처리 기준

`web_target` 은 결과물이 아니라 피험체다. 결함을 발견마다 고치면 하네스 작업이
앱 작업으로 전이된다. 기준은 **"이 실패가 하네스에 교훈을 주는가"** 다.

| 사례 | 판정 | 조치 |
|---|---|---|
| 테스트 라벨이 명세와 불일치 | 측정 도구 오류 | 고침 |
| 명세에 없는 것을 단정하는 테스트 | 측정 도구 오류 | 고침 |
| 취약한 셀렉터(`data-testid` 요구) | 측정 도구 오류 | 역할 기반 질의로 고침 — **앱에 훅 추가 안 함** |
| 다른 기능 요구와 모순되는 테스트 | 측정 도구 오류 | 고침 |
| **앱의 인증 설계 결함 4건** | 하네스 교훈 없음 | **고치지 않음** — `test.fixme` + 사유 기록 |

마지막 항목이 핵심이다. `AuthContext` 가 클라이언트에서 디코드한 `isAdmin` 을 신뢰하고,
`AuthContext.login()` 은 죽은 코드이며, 로그인 후 전체 리로드를 한다. 고치려면 인증 흐름
전체 재설계이고 하네스에는 교훈이 없다. **테스트를 앱에 맞춰 약화시키는 것이 가장 나쁜
선택**이므로 신호만 보존했다 (TS-014).

---

## 9. 상태 파일

| 경로 | 추적 | 내용 |
|---|---|---|
| `web_target/features.json` | O | 기능 75개 + `passes` + `verification` 증거 — **진실의 원천** |
| `web_target/src/routes.ts` | O | 보호 경로 목록의 단일 출처 (앱과 테스트가 공유, TS-013) |
| `troubleshooting/` | O | 실패 모드 14건 + `evidence/` 1차 자료 |
| `.harness_memory/<session>/` | O | Reflexion 반성 기록. 같은 세션 ID 로 재실행 시 주입된다 |
| `.claude/skills/harness/` | O | 토큰 없는 모드의 절차 |
| `harness_runtime.log` | X | 나이트 시프트 출력. `cli report` 의 입력 데이터 |

---

## 10. 현재 상태

```
기능 6/75 통과 — 전부 증거 기록 보유
jest 51/51 (7 suites) · E2E 14 통과 / 4 보류 / 실패 0
lint exit 0 · build exit 0 · tsc 오류 0
하네스 회귀 176건 (repro_ts005/006/008/009/010) 전부 통과
```

| 기능 | 근거 테스트 | 단계 커버리지 |
|---|---|---|
| F-001 이메일/비밀번호 로그인 | 3건 | 0/6 |
| F-002 잘못된 자격증명 오류 | 3건 | 0/5 |
| F-003 이메일 유효성 검사 | 5건 | 0/5 |
| F-004 로그아웃 | 4건 | 4/5 |
| F-005 미인증 리다이렉트 | 24건 | **3/3** |
| F-018 주간 완료 차트 | 2건 | **2/2** |

`step` 수준으로 돌리면 F-005·F-018 둘만 통과한다.

### 회귀 검증

```bash
python repro_ts005.py   # LLM 오류 분류·백오프·종료 코드      37/37
python repro_ts006.py   # 증거 게이트 정책                    32/32
python repro_ts008.py   # 명세-테스트 연결 판정               49/49
python repro_ts009.py   # 측정 계층 + 종료 상태 기록          36/36
python repro_ts010.py   # 토큰 없는 모드 의존성 독립          22/22

cd web_target
npm run lint       # exit 0
npm run build      # exit 0 — dist/ 생성
npm test           # 51/51 통과, 커버리지 < 임계 80% 이므로 exit 1
npm run test:e2e   # exit 0 — 14 통과 / 4 보류
npx jest . --no-coverage   # 게이트와 같은 기준
```

`npm test` 는 커버리지 임계값 때문에 테스트가 전부 통과해도 exit 1 이다.
**테스트 실패와 커버리지 미달을 구분할 것.**
E2E(`*.spec.ts`)는 **게이트에 계수되지 않는다** — 게이트는 jest 만 실행한다.

### 알려진 제약

- Gemini 프로젝트가 월 지출 한도 소진 → 유료 모드 실행 불가. 해제하거나 `flash` 로 재실행.
- **기능당 토큰·비용을 기록하지 않는다** — "하네스가 비용만큼 값을 했는가"를 계산할 수 없다.
- **하네스 유무의 A/B 를 돌리지 못했다** — §6 은 *게이트 기준*의 A/B 이고, 하네스 전체의
  효과는 미측정이다. 설계는 서 있으나 수치가 없다.
- Evaluator 의 LLM 채점과 `EVAL_WEIGHTS` / 75점 임계는 **근거 없는 상수**다.
  단, `features.json` 의 플래그는 그 점수에 의존하지 않는다 — 분리되어 있다.
- 태그된 테스트가 **제대로** 검증하는지는 게이트가 보지 않는다.
  `expect(true).toBe(true)` 에 태그를 붙이면 통과한다.
- 커버리지 임계 80% 대비 실측 미달.

---

## 11. 실패 모드 카탈로그

| ID | 제목 |
|---|---|
| TS-001 | `night_shift.py` 가 `features.json` 을 찾지 못하고 조용히 "완료" 출력 |
| TS-002 | Windows cp949 콘솔에서 이모지 출력이 `UnicodeEncodeError` 로 중단 |
| TS-003 | subprocess 가 cp949 출력을 UTF-8 로 디코딩하다 `_readerthread` 크래시 |
| TS-004 | 도구 없이 텍스트만 응답하면 그래프가 조용히 종료되어 exit 0 으로 위장 성공 |
| TS-005 | LLM 쿼터 초과(429)가 트레이스백으로 터지며 멀쩡한 기능들을 stuck 으로 마킹 |
| TS-006 | 에이전트가 테스트 증거 없이 자가 채점 — `run_tests` 는 Windows 에서 한 번도 동작하지 않았다 |
| TS-007 | 체크포인터 영속 설정이 죽은 설정 — 플래그를 전달하지 않아 항상 `InMemorySaver` |
| TS-008 | "스위트 녹색"을 "이 기능이 검증됨"으로 오인 — 게이트가 기능과 테스트를 연결하지 않았다 |
| TS-009 | 실행 15회 중 9회가 종료 상태를 남기지 않아 사후 측정의 60%가 맹점 |
| TS-010 | 하네스의 가치는 이미 토큰을 쓰지 않았다 — 유료 API를 추론 엔진에서 제거 |
| TS-011 | 라우트 가드가 `isLoading` 을 무시해 새로고침마다 로그아웃 + `?redirect=` 오픈 리다이렉트 |
| TS-012 | `package.json` 이 광고하는 명령 3개(lint/build/test:e2e)가 전부 동작하지 않았다 |
| TS-013 | 단위 테스트가 자기가 만든 라우트를 검증해 F-005 가 실 브라우저에서 전혀 동작하지 않았다 |
| TS-014 | 태그가 엉뚱한 기능을 가리켜도 게이트가 보지 못한다 — 피험체 결함은 어디까지 고치는가 |

전체 목록: [troubleshooting/INDEX.md](troubleshooting/INDEX.md)

**반복된 패턴**: "선언과 실제의 불일치가 실행되지 않아 유지된다" — 네 번 나왔다
(TS-001 루트 `features.json`, `init.sh` 의 `PROJECT_ROOT`, TS-006 의 `run_tests`, TS-012 의 3건).
하위 디렉터리로 프로젝트를 옮긴 뒤 루트에 남은 설정 파일을 전수 점검하지 않은 결과다.

---

## 12. 참고

- 외부 프로젝트 비교 분석과 기준의 근거: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)
- Reflexion 이 오류 신호 없이 근본 원인을 날조한 1차 증거:
  [troubleshooting/evidence/F-004-reflexion-confabulation/](troubleshooting/evidence/F-004-reflexion-confabulation/)

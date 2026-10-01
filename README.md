# 하네스 엔지니어링 (Harness Engineering)

> **자율 코딩 에이전트를 "돌리는 법"이 아니라 "운영하는 법"을 만드는 프로젝트.**

## 1. 이 프로젝트의 목적

LLM 에이전트에게 코드를 쓰게 하는 것은 쉽다. 어려운 것은 **사람이 보지 않는 동안
에이전트가 만든 결과를 신뢰할 수 있게 만드는 것**이다. 이 저장소는 그 신뢰를 만드는
장치(harness)를 구현하고, 그 장치가 깨지는 방식을 전부 기록한다.

### 결과물이 무엇이고 무엇이 아닌가

| | |
|---|---|
| **결과물이다** | `harness/` — 에이전트 실행·검증·중단·재개를 관리하는 운영 계층 |
| **결과물이다** | `troubleshooting/` — 무인 운영에서 실제로 터진 실패 모드 9건의 재현·원인·수정·검증 기록 |
| **결과물이 아니다** | `web_target/` — 투두 앱. 하네스를 시험하기 위한 **피험체**이자 벤치마크 과제 |

`web_target` 의 기능 75개(`features.json`)는 목표가 아니라 **측정 수단**이다.
"에이전트가 기능 몇 개를 몇 번 시도해서 얼마의 비용으로 통과시켰는가"가 이 프로젝트가
생산하는 데이터다.

### 설계 원칙 — 네 가지 불신

하네스의 거의 모든 코드는 아래 네 문장 중 하나에서 나왔다.

1. **에이전트의 자기 보고를 믿지 않는다.** "구현했다"는 말은 증거가 아니다.
   완료 플래그는 도구가 테스트를 실행해 입증한 뒤에만 기록된다 (TS-006).
   더 나아가 **스위트가 녹색이라는 사실도 그 기능의 증거가 아니다** — 해당 기능 ID 를
   인용하는 통과 테스트를 요구한다 (TS-008).
2. **조용한 성공을 믿지 않는다.** 도구 호출 없이 끝난 턴, 종료 코드 0으로 위장한 중단은
   모두 재시도 가능한 실패로 취급한다 (TS-004).
3. **실패의 원인을 과제에 전가하지 않는다.** 쿼터 초과·인증 실패는 기능의 잘못이 아니므로
   attempt 를 소모하지 않고 런 전체를 중단한다 (TS-005).
4. **비가역적 행위는 사람이 승인한다.** 도구는 3계층 권한을 갖고,
   `IRREVERSIBLE` 은 그래프를 멈춰 승인을 기다린다.

---

## 2. 어떻게 돌아가는가

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

| 에이전트 | 파일 | 역할 |
|---|---|---|
| P-01 Orchestrator | `harness/nodes/agents.py` | 다음 작업 선택, 위임 |
| P-02 Initializer | 〃 | 최초 1회 환경 구성 |
| P-03 Coder | 〃 | ReAct 루프로 실제 구현 |
| P-04 Evaluator | 〃 | **도구 실행 기록만 보고** 채점 (기능40/품질30/성능20/보안10, 75점 합격) |
| P-05 Reflector | 〃 | 5-Why 반성 → 에피소드 메모리 |

**도구 권한 3계층** (`harness/tools.py`, 총 15종)

| 계층 | 도구 | 정책 |
|---|---|---|
| `READ_ONLY` | `read_file`, `list_directory`, `read_features`, `read_progress`, `list_troubles`, `read_trouble` | 승인 불필요 |
| `STATEFUL` | `write_file`, `run_tests`, `bash_command`, `git_commit`, `update_features`, `write_progress`, `log_trouble` | 감사 로그 |
| `IRREVERSIBLE` | `deploy_prod`, `delete_resource` | **라우터가 `human_check` 로 강제 분기** |

---

## 3. 설치

```bash
# 1) 파이썬 의존성 (하네스)
pip install -r requirements.txt

# 2) 대상 앱 의존성
cd web_target && npm install && cd ..

# 3) API 키 — .env 파일에 작성 (절대 커밋 금지, .gitignore 에 등록되어 있음)
#    GOOGLE_API_KEY=your_key_here

# 또는 위 전부를 한 번에
bash scripts/init.sh --install
```

`bash scripts/init.sh` 는 의존성 설치 + 개발 서버 기동 + 스모크 테스트까지 수행한다.

---

## 4. 사용법

### 4.1 기능 하나를 구현시킨다

```bash
python main.py --task "사용자가 로그아웃할 수 있다" --project ./web_target
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--task` | (필수) | 구현할 기능 설명 |
| `--project` | `./web_target` | 대상 프로젝트 루트 |
| `--session` | 자동 생성 | 세션 ID. **같은 ID 를 쓰면 이전 반성 메모리를 이어받는다** |
| `--max-retry` | 5 | Reflexion 반복 상한 |
| `--no-stream` | off | 단계별 실시간 출력 비활성화 |
| `--visualize` | off | 그래프를 `harness_graph.png` 로 저장 |

### 4.2 무인 연속 실행 (나이트 시프트)

```bash
python night_shift.py
```

`web_target/features.json` 에서 `passes: false` 인 기능을 순서대로 집어 실행한다.
기능당 최대 3회 시도, 작업당 30분 타임아웃, 전체 로그는 `harness_runtime.log`.
기능별로 `feature-<ID>` 세션 ID 를 고정하므로 재시도 시 반성 메모리가 누적된다.

### 4.3 종료 코드 — 실패의 책임 소재를 구분한다

| 코드 | 의미 | `night_shift` 의 반응 |
|---|---|---|
| 0 | `done` — 구현 + 평가 PASS | 다음 기능으로 |
| 1 | `escalated` / `cancelled` | attempt 소모, 3회 초과 시 stuck |
| 2 | 그 외 (silent-abort 포함) | attempt 소모 |
| **3** | **LLM 공급자 사용 불가 (인프라)** | **attempt 미소모 + 런 전체 즉시 중단** |

코드 3 은 쿼터 초과·인증 실패·백오프 소진이다. 기능의 잘못이 아니므로
`features.json` 은 그대로 보존되고, 원인을 해결한 뒤 재실행하면 이어서 진행한다.

### 4.4 완료 플래그는 증거가 있어야 기록된다

`update_features(passes=true)` 는 **도구가 직접 전체 테스트 스위트를 실행**하고,
아래 두 조건을 모두 만족할 때만 플래그를 쓴다 (TS-008).

1. 스위트에 실패 테스트가 0건 — 다른 기능을 깨뜨리지 않았다
2. **해당 기능 ID 를 이름에 포함한 통과 테스트가 1개 이상**

스위트가 녹색이어도 기능 ID 태그가 없으면 거부된다. 녹색 스위트는 '프로젝트가 건강하다'의
증거이지 '이 기능이 동작한다'의 증거가 아니기 때문이다.

**태그 규약** — 새로 만든 규칙이 아니라 `LoginForm.test.tsx` 가 이미 쓰던 관행이다:

```ts
describe('F-004: 사용자가 로그아웃할 수 있다', ...)        // 기능 태그
test('F-004.5: 로그아웃 시 auth_token 이 삭제된다', ...)   // 단계 태그 (명세 steps 5번)
```

통과 시 **무엇을 근거로 통과시켰는지**가 함께 기록된다.

```json
{
  "id": "F-004",
  "passes": true,
  "verification": {
    "verified_at": "2026-10-01T19:04:05",
    "verified_by": "update_features/jest",
    "level": "feature",
    "suite": {
      "total": 27,
      "passed": 27,
      "failed": 0,
      "suites_total": 5,
      "suites_failed": 0
    },
    "summary": "suite 27/27 passed | tagged 4 passed | steps 4/5 covered",
    "evidence_tests": [
      "AuthContext F-004.5: logout 함수는 localStorage에서 auth_token을 제거해야 한다",
      "UserMenu F-004.2: 메뉴 버튼 클릭 시 드롭다운 메뉴가 열리고 닫혀야 합니다",
      "UserMenu F-004.3 F-004.4: Logout 버튼 클릭 시 useAuth의 logout 함수가 호출되고 /login 페이지로 이동해야 합니다",
      "UserMenu F-004.3 F-004.4: 로그아웃 버튼을 클릭하면 logout 함수가 호출되고 /login으로 이동한다"
    ],
    "steps_covered": [
      2,
      3,
      4,
      5
    ],
    "steps_uncovered": [
      1
    ]
  }
}
```

- 테스트 경로는 **도구가 `"."` 로 고정**한다 — 에이전트가 쉬운 테스트만 골라
  통과를 조작할 수 없다.
- 엄격도는 `HARNESS_EVIDENCE_LEVEL` 로 조정한다: `suite`(스위트만) /
  `feature`(기본) / `step`(명세 전 단계가 단계 태그로 덮여야 통과).
  단계 커버리지는 어느 수준이든 **측정해 기록**한다 — 위 예시의 `steps_uncovered` 가 그것이다.
- 커버리지 임계값은 게이트 대상이 **아니다** (현재 37% vs 설정 80% — 게이팅하면 전부 영구 미완성).
- 끄는 방법은 운영자에게만 있다: `HARNESS_REQUIRE_TEST_EVIDENCE=false` (디버깅 전용).
  끈 상태로 기록된 플래그에는 경고가 붙는다.

### 4.5 트러블슈팅 로그는 에이전트도 쓴다

```bash
python -c "from harness.tools import list_troubles; print(list_troubles.invoke({'status':'all'}))"
```

`log_trouble` / `list_troubles` / `read_trouble` 은 에이전트에게 노출된 도구다.
`INDEX.md` 는 `list_troubles` 호출 시 자동 재생성된다. 새 실패 모드를 만나면
`troubleshooting/_template.md` 형식(증상 → 근본 원인 → 수정 → 검증 → 예방)으로 기록한다.

### 4.6 하네스 자체를 측정한다

```bash
python -m harness.metrics --project ./web_target     # 사람이 읽는 표
python -m harness.metrics --json                     # 기계가 읽는 JSON
```

증거 게이트의 **판별력**(기준을 바꿨을 때 통과 건수가 얼마나 줄어드는가)과
실행 로그의 결과 분포를 집계한다. LLM 호출이 없어 API 쿼터와 무관하게 재현된다.

현재 수치 (저자 측정, 독립 검증 필요):

| 증거 수준 | 통과 | 통과율 |
|---|---|---|
| `suite` (TS-006 동작) | 75 / 75 | 100.0% |
| `feature` (기본) | 5 / 75 | 6.7% |
| `step` | 1 / 75 | 1.3% |

**판별력 93.3%** — `suite` 기준이 통과시킨 75건 중 70건은 근거 없는 통과였다.
모든 입력을 통과시키는 기준은 기준이 아니라는 원칙([비교 분석](docs/comparison-revfactory.md))을
우리 게이트에 적용한 결과다.

### 4.7 회귀 검증

```bash
python repro_ts005.py                      # LLM 오류 분류/백오프/종료 코드   37/37
python repro_ts006.py                      # 증거 게이트 정책                 32/32
python repro_ts008.py                      # 명세-테스트 연결 판정 로직       49/49
python repro_ts009.py                      # 측정 계층 + 종료 상태 기록       36/36
cd web_target && npx jest . --no-coverage  # 대상 앱 스위트                   27/27
```

`npm test` 는 커버리지 임계값(80%) 때문에 테스트가 전부 통과해도 exit 1 이다.
**테스트 실패와 커버리지 미달을 구분할 것** — 게이트와 같은 기준으로 보려면 `--no-coverage`.

---

## 5. 환경변수

`.env` 또는 셸 환경에 설정한다. 전부 `config.py` 에서 읽는다.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `GOOGLE_API_KEY` | (없음) | **필수.** Gemini API 키 |
| `HARNESS_LLM_MODEL` | `gemini-2.5-pro` | 모델. 한도 초과 시 `gemini-2.5-flash` 로 계속 가능 |
| `HARNESS_LLM_MAX_TOKENS` | 4096 | 응답 상한 |
| `HARNESS_LLM_MAX_ATTEMPTS` | 4 | 일시 오류 재시도 횟수 (쿼터 초과는 재시도 안 함) |
| `HARNESS_LLM_BACKOFF_BASE` | 5 | 백오프 기준 초 |
| `HARNESS_LLM_BACKOFF_MAX` | 60 | 백오프 상한 초 |
| `HARNESS_MAX_RETRY` | 5 | Reflexion 반복 상한 |
| `HARNESS_EVAL_THRESHOLD` | 75 | Evaluator 합격선 |
| `HARNESS_REQUIRE_TEST_EVIDENCE` | `true` | 완료 플래그의 테스트 증거 게이트 |
| `HARNESS_EVIDENCE_LEVEL` | `feature` | 증거 엄격도: `suite` / `feature` / `step` |
| `HARNESS_PERSISTENT` | `false` | 체크포인터 영속화 (아래 주의 참조) |
| `DATABASE_URL` | (없음) | Postgres 체크포인터 접속 문자열 |
| `HARNESS_MEMORY_DIR` | `./.harness_memory` | 에피소드 메모리 경로 |
| `HARNESS_CONTEXT_THRESHOLD` | 150000 | 컨텍스트 압축 임계 토큰 |
| `DEV_PORT` / `API_PORT` | 5173 / 3001 | 개발 서버 포트 |
| `DEPLOY_APPROVAL_TOKEN` | (없음) | `IRREVERSIBLE` 도구 승인 토큰 |

> **영속화 주의**: `langgraph-checkpoint-postgres` 가 설치되어 있지 않으면
> `HARNESS_PERSISTENT=true` 여도 경고와 함께 `InMemorySaver` 로 폴백한다
> (프로세스 간 재개 불가, `human_check` 대기 상태도 프로세스와 함께 소멸).
> 활성화: `pip install langgraph-checkpoint-postgres psycopg[binary]` (TS-007)

---

## 6. 상태 파일 지도

| 경로 | 성격 | 내용 |
|---|---|---|
| `web_target/features.json` | **진실의 원천** | 기능 75개 + `passes` + `verification` 증거 |
| `web_target/gemini-progress.txt` | 추적 | 세션 핸드오프 기록 (P-17) |
| `harness_runtime.log` | 비추적 | 나이트 시프트 전체 출력 |
| `.harness_memory/<session>/` | 추적 | Reflexion 반성 기록. 같은 세션 ID 로 재실행하면 주입된다 |
| `troubleshooting/` | 추적 | 실패 모드 카탈로그 + `evidence/` 1차 자료 |

---

## 7. 현재 상태와 다음 단계

- **구현 완료**: 5 / 75 기능 — **전부 증거 기록을 보유**한다.
  TS-008 재감사에서 F-015(순위표)는 테스트가 전무해 **통과를 회수**했고,
  F-018(주간 차트)은 명세 2단계를 모두 검증하는 테스트가 있어 **새로 부여**했다.

| 기능 | 근거 테스트 | 단계 커버리지 | 설명 |
|---|---|---|---|
| F-001 | 3건 | 0/6 | 사용자가 이메일과 비밀번호로 로그인할 수 있다 |
| F-002 | 3건 | 0/5 | 잘못된 자격증명으로 로그인 시 오류 메시지가 표시된 |
| F-003 | 5건 | 0/5 | 이메일 형식이 잘못된 경우 유효성 검사 오류가 표시 |
| F-004 | 4건 | 4/5 | 사용자가 로그아웃할 수 있다 |
| F-018 | 2건 | 2/2 | 대시보드에 주간 완료 통계 차트가 표시된다 |

  `step` 수준(최고 엄격도)으로 돌리면 현재 통과하는 것은 F-018 하나뿐이다 —
  나머지는 기능 태그만 있고 단계 태그가 없다.
- **대상 앱 테스트**: 27 passed / 27 total (5 suites).
- **알려진 제약**:
  - Gemini 프로젝트가 월 지출 한도에 걸려 있다 → 해제하거나 `gemini-2.5-flash` 로 재실행.
  - 체크포인터 영속 백엔드 미설치 → 프로세스 간 재개 불가.
  - `tsc --noEmit` 오류 5건 (대상 앱의 `api.ts` 의 `import.meta.env` 타입, `handlers.ts` 의 msw 미설치).
  - 커버리지 37% vs 설정 임계 80%.
- **측정 아이디어**: 같은 75개 기능을 모델/프롬프트만 바꿔 재실행하면
  기능당 시도 횟수·비용·실패 유형 분포를 비교할 수 있다. 증거 게이트가 켜져 있어야
  그 수치가 의미를 갖는다.

---

## 8. 참고

- 실패 모드 전체 목록: [troubleshooting/INDEX.md](troubleshooting/INDEX.md)
- 외부 프로젝트 비교 분석과 기준의 근거: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)
- Reflexion 이 오류 신호 없이 근본 원인을 날조한 사례:
  [troubleshooting/evidence/F-004-reflexion-confabulation/](troubleshooting/evidence/F-004-reflexion-confabulation/)

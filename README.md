# 하네스 엔지니어링 (Harness Engineering)

**한국어** · [English](README_EN.md)

[![CI](https://github.com/bean-baek/harness_project/actions/workflows/ci.yml/badge.svg)](https://github.com/bean-baek/harness_project/actions/workflows/ci.yml)

> **자율 코딩 에이전트를 "돌리는 법"이 아니라 "운영하는 법"을 만드는 프로젝트.**

LLM 에이전트에게 코드를 쓰게 하는 것은 쉽다. 어려운 것은 **사람이 보지 않는 동안
에이전트가 만든 결과를 신뢰할 수 있게 만드는 것**이다. 이 저장소는 그 신뢰를 만드는
장치(harness)를 구현하고, 그 장치가 깨지는 방식을 전부 기록한다.

---

## 1. 결과물이 무엇이고 무엇이 아닌가

| | |
|---|---|
| **결과물이다** | `harness/` — 에이전트 실행·검증·측정·중단을 관리하는 운영 계층 |
| **결과물이다** | `troubleshooting/` — 실제로 터진 실패 모드 **22건**의 재현·원인·수정·검증 기록 |
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

### 디렉터리 구조

```
harness/              운영 계층 — 게이트·측정·런너·검수 (결과물)
  verify.py           증거 게이트 정책 (단일 소유자)
  runner.py           생태계에 묶인 전부 — jest·vitest·pytest
  project.py          .harness.json 선언 + 프로젝트 검수
  inspect.py          객관 지표(불변식) 추출
  independence.py     증거 독립성 — 테스트가 구조를 자급하는가
  deadcode.py         하네스 자기 감사 — 죽은 설정·고아 코드
  tags.py metrics.py mutate.py cli.py
  graph.py router.py state.py tools.py prompts.py memory.py llm_errors.py
  nodes/agents.py     5개 에이전트 노드 (유료 경로)
verification/         회귀 검증 617건 — 실패 모드 하나당 스크립트 하나
troubleshooting/      실패 모드 22건 기록 + evidence/ 1차 자료
web_target/           피험체 투두 앱 (결과물 아님)
.harness_memory/      Reflexion 1차 자료 — 재생성 불가, 보존
docs/ scripts/ .claude/skills/harness/
config.py exit_codes.py main.py night_shift.py
```

회귀 검증은 **루트에서 실행한다** — 일부 검증이 `web_target` 을 상대 경로로 쓴다
([verification/README.md](verification/README.md)).

---

## 2. 두 가지 실행 모드

| | 토큰 없는 모드 (권장) | 유료 API 모드 |
|---|---|---|
| 추론 엔진 | **Claude Code 세션** (구독 비용에 포함) | Gemini API (종량 과금) |
| 강제 | `python -m harness.cli` (결정론적) | 동일한 게이트 + LangGraph 라우터 |
| 무인 실행 | 불가 — 사람이 세션을 열어야 한다 | **가능** (`night_shift.py`, 30분 타임아웃) |
| 의존성 | 표준 라이브러리 + jest | langchain, langgraph, API 키 |
| 검증 | 회귀 326건 + 실제 jest | **스모크 78건** (LLM 스텁, 토큰 0 — TS-018) |

**왜 분리했는가**: 코드를 성격별로 세어보니 결정론적 기계(게이트·측정·태그 린터·도구·CLI)
**2,703줄**은 토큰을 전혀 쓰지 않고, **2,357줄**만이 유료 API를 돌리기 위해 존재한다.
**가치 있는 쪽은 이미 무료였다** (TS-010 — 당시 측정은 2,060줄, 이후 측정·린터 추가로 늘었다).

**유료 경로는 실제로 돌았고, 이제 검증된다**: `.harness_memory/` 에 2026-04-14 자
Reflexion 산출물 67개가 있고 TS-004/005/007 은 돌려봐야만 발견된 실패다. 그런데 그 뒤
6개월간 아무 테스트도 그 경로를 거치지 않아 — 커버리지로 재어보니 `graph.py`·`router.py`·
`agents.py`·`memory.py` 359줄 중 **실행되는 로직이 4줄**이었다 — TS-017 의 리팩터가 그
위에서 눈을 감고 진행됐다. `repro_ts018.py` 가 LLM 을 스텁으로 바꿔 그래프를 끝까지 돌려
그 맹점을 없앴고, **그 즉시 실제 버그 2건을 찾아냈다** (§11 TS-018).

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
python -m harness.cli mutate F-005   # 증거가 실제로 무는지 측정 (느림, 게이트 아님)
python -m harness.cli report         # 판별력 + 게이트 판정 집계 + 실행 로그
python -m harness.cli init           # 프로젝트 검수 → .harness.json 생성 (TS-017)
python -m harness.cli inspect        # 객관 지표 추출 + 의도가 필요한 항목 분리
python -m harness.cli deadcode       # 하네스 자기 감사 — 죽은 설정·고아 코드 (TS-019)
python -m harness.cli independence   # 증거 독립성 — 테스트가 구조를 자급하는가 (TS-020)
```

`verify` / `mark` / `unmark` 는 판정마다 `harness_runtime.log` 에 기록을 남긴다
(`--log` 로 경로 변경, `--no-log` 로 비활성화). 그 기록이 아래 §6 의 집계 입력이다.

Claude Code 세션에서는 [.claude/skills/harness/SKILL.md](.claude/skills/harness/SKILL.md) 가
절차를 안내한다 — 네 가지 불신 → 구현 → 태그 테스트 → 게이트 → 자기평가 → 기록.
`--project` 는 서브명령 앞뒤 어디에 써도 된다.

### 4.1 완료 플래그는 증거가 있어야 기록된다

`mark` 는 **도구가 직접 전체 스위트를 실행**하고, 두 조건을 모두 만족할 때만 플래그를 쓴다.

1. 스위트에 실패 테스트 0건 — 다른 기능을 깨뜨리지 않았다
2. **해당 기능 ID 를 이름에 포함한 통과 테스트가 1개 이상**
3. **그 태그 테스트가 비(非)테스트 소스를 1줄 이상 실행** (TS-016)

3번이 없으면 `test('F-006: x', () => expect(true).toBe(true))` 가 완벽한 증거로
계수된다 — 실제로 심어서 통과하는 것을 확인했다.

증거의 **출처**는 게이트가 묻지 않는다 — 세 조건은 구현자가 쓴 단위 테스트 하나로
전부 만족된다. 그 바깥 껍질은 `cli independence` 가 보고한다 (§4.5, TS-020).

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
- 끄는 방법은 운영자에게만 있다: `HARNESS_REQUIRE_TEST_EVIDENCE=false`,
  `HARNESS_REQUIRE_EVIDENCE_COVERAGE=false` (디버깅 전용).
- 증거가 실행한 소스 파일이 `evidence_sources` 로 기록된다 —
  F-005 → `ProtectedRoute.tsx (17)`, `LoginForm.tsx (13)` 처럼 귀속이 드러난다.

### 4.2 증거가 실제로 무는가 — 돌연변이 측정 (TS-016)

```bash
python -m harness.cli mutate F-005
```

커버리지는 "소스를 실행한다"까지만 보장한다. 실행하지만 아무것도 단정하지 않는 테스트는
여전히 통과한다. 그걸 묻는 유일한 방법은 **결함을 일부러 넣어보는 것**이다.

구현에 구문 유지 변이(비교 반전·논리 반전·조건 무력화 등)를 넣고, `tsc` 로 유효성을 확인한 뒤
태그 테스트가 실패하는지 본다. 원본은 `finally` 에서 항상 복원한다.

**게이트로 쓸 수 있다 (기본은 꺼짐, TS-021).** `HARNESS_REQUIRE_MUTATION_EVIDENCE=true`
로 켜면 `mark` 가 **유효한 변이 1개 이상을 잡는지** 요구한다. TS-016 의 "소스 1줄 이상
실행"과 같은 모양의 최솟값이며 비율이 아니다 — 변이 대상을 커버리지로 고르므로 다른 기능이
소유한 파일이 섞이고, 그 혼합에 비율을 적용하면 `EVAL_WEIGHTS` 와 같은 근거 없는 상수가 된다.

세 경우를 구분한다: 도구가 돌지 않으면 **거부**(측정 실패는 통과가 아니다), 변이할 구문이
없으면 **기록만**(측정 **대상 부재**는 측정 **실패**와 다르다), 잡음 0건이면 **거부**.

기본값이 꺼짐인 이유는 비용이다 — `mark` 가 11초에서 **42초**로 늘어난다(실측).

**비용 실측 (웜 캐시)** — 콜드로 재면 10배 틀린다:

| 단계 | 콜드 | 웜 |
|---|---|---|
| `tsc --noEmit` | 10.8초 | **1.9초** |
| 범위 jest | 18.4초 | **2.8초** |

jest 를 **먼저** 돌리고 tsc 는 실패했을 때만 돌린다 — 통과한 변이는 컴파일된 것이므로
유효성을 다시 물을 필요가 없다. 생존 변이당 1.9초 절감.

**연산자가 구문을 파괴하고 있었다 (TS-021).** `>` → `>=` 규칙이 **190곳**에 매칭됐고
진짜 비교는 **3곳**뿐이었다 — 나머지는 JSX(108곳)와 제네릭(32곳)이라
`React.FC<Props>` 가 `React.FC<Props>=` 가 됐다. `if (X)` → `if (false)` 는 중첩 괄호에서
`if (false))` 로 깨졌다. 변이가 테스트를 시험하는 게 아니라 **컴파일러를 시험했고**,
'폐기' 집계가 그 사실을 가렸다.

**탐지 범위도 두 군데 막혀 있었다 (TS-022).**

표본이 **파일 앞머리에 고정**돼 있었다 — 규칙마다 `lines[0]` 하나만 썼다.
`LoginForm.tsx` 는 변이 지점 19곳이 **전부 실행되는 줄**인데 3곳만 시도됐고,
32번 줄이 항상 이기므로 55·56번 줄 — `safeRedirectTarget` 의 오픈 리다이렉트 가드,
즉 **TS-011 의 수정** — 은 한 번도 검사되지 않았다. 전체 도달률은 59곳 중 23곳(39%)이었다.

`select_spread()` 로 후보를 전부 모은 뒤 **등간격**으로 뽑는다(무작위가 아닌 이유:
재현 가능해야 회귀로 고정할 수 있다). 예산 3 → `[0, 9, 18]`.

연산자가 **배열 선언에 닿지 못했다.** `routes.ts` 는 증거가 6줄 실행하는데 변이 지점이
0곳이다 — 배열에는 비교·논리·조건이 없다. 그래서 **TS-013 의 버그 모양**을 주입할 수단이
없었다. 손으로 실험했다:

| 제거한 멤버 | 결과 | 스위트 |
|---|---|---|
| `/` | **생존** | 49 통과 / 0 실패 |
| `/dashboard` | 잡음 | 48 통과 / 1 실패 |
| `/profile` | **생존** | 49 통과 / 0 실패 |
| `/settings` | **생존** | 49 통과 / 0 실패 |

**보호 경로 4개 중 3개를 지워도 전부 통과한다** — `test.each(PROTECTED_PATHS)` 는 목록이
줄면 **덜 돌 뿐**이다. 그 동안 사다리 네 칸(태그·커버리지·독립성·돌연변이)이 **전부 통과**한다.

`drop_member()` 연산자가 그 구멍을 메운다. `independence` 가 찾아 둔 "앱이 선언한 단일
출처 컬렉션"을 재사용한다 — 두 모듈이 합쳐져 **선언의 결함**을 주입한다.

**`types` 상태** — `/dashboard` 제거는 처음에 '폐기'로 분류됐다. 그런데 `drop_member` 는
배열 리터럴을 유지하므로 구문은 **구성상 유효하다.** tsc 가 실패한 이유는
`Record<ProtectedPath, …>` 가 목록과 소비처를 타입으로 묶었기 때문 — **타입 수준의 감지**다.
증거 점수의 분자에는 넣지 않되(잡은 것은 테스트가 아니다) '폐기'로 묻지도 않는다
(구조적 보호가 있다는 사실이 사라진다).

**표본 크기를 함께 출력한다.** `후보 27곳 중 16곳 시도` — 이것이 없으면 "33%" 가 몇 개
표본에 근거한 수치인지 알 수 없다. `--max-per-file` / `--max-collection` 로 늘린다.

수정 후 F-005: **점수 33%** (잡음 5 / 생존 10 / 폐기 0 / 타입이 잡음 1), 표본 16/27.
점수가 내려간 것이 개선이다 — 3표본의 40%는 앞머리에 편향된 **과대평가**였고,
표본을 10 → 16 으로 늘려도 33%로 안정한다.

**새로 드러난 것**: `LoginForm.tsx:32·89·188` 생존(퍼뜨린 표본이 처음 도달), 그리고
`PROTECTED_PATHS` 의 `/`·`/profile`·`/settings` 가 **테스트로 고정되어 있지 않다**는 사실.


### 4.3 다른 프로젝트에 붙이기 (TS-017)

생태계에 묶인 코드는 `harness/runner.py` 하나다. 나머지(판정 정책·태그·측정·CLI)는
런너를 모른다. 프로젝트별 규약은 **`.harness.json`** 이 선언한다.

```bash
# 1) 검수 — 무엇을 어떻게 검사할지 추론하고 근거를 출력 (쓰지 않는다)
python -m harness.cli init --harness-root /path/to/project --dry-run

# 2) 맞으면 설정 생성
python -m harness.cli init --harness-root /path/to/project
```

```jsonc
// .harness.json — 선언된 키가 추론을 이긴다. 틀린 것만 적으면 된다.
{
  "target": "web_target",              // 검사 대상 앱 경로
  "runner": "jest",                    // jest | vitest | pytest
  "spec": "features.json",             // 명세 파일
  "id_pattern": "F-\\d{3}",            // 기능 ID 형식
  "unit_suffixes": [".test.ts", ".test.tsx"],   // 증거로 계수하는 테스트
  "e2e_suffixes": [".spec.ts"],                 // 증거로 계수하지 않는다 (런너가 다름)
  "source_dirs": ["src"],
  "typecheck": ["npx", "--no-install", "tsc", "--noEmit"]
}
```

설정 파일이 **없으면 기본값은 외부화 이전의 하드코딩과 같다** — 기존 사용자의 동작은
변하지 않는다(회귀 236건이 설정 추가 전/후 모두 통과하는 것으로 확인).

출력은 값마다 출처를 표시한다. **`기본값`은 "근거 없이 골랐다"는 자백이다** —
그 줄만 `.harness.json` 에 적어 덮으면 된다.

```
[실측] runner = vitest
       └ package.json 의 의존성에 vitest 가 있습니다
[기본] typecheck = (없음)
       └ tsconfig.json 이 없습니다 — 돌연변이의 유효성 확인을 건너뜁니다
```

#### 다른 생태계 추가

`harness/runner.py` 에 `Runner` 하위 클래스를 넣고 네 연산만 구현한다.

| 연산 | 무엇을 돌려주나 |
|---|---|
| `run_all()` | 전체 스위트 (종료코드, 출력) |
| `results()` | 테스트 **개별 이름과 상태** — 게이트가 기능 ID 를 인용하는 테스트를 찾는다 |
| `coverage(files, pattern)` | 주어진 테스트만 돌렸을 때 **소스별 실행 statement 수** |
| `typechecks()` | 코드가 정적으로 유효한가 (돌연변이 유효성 확인) |

모든 연산은 `(값, 진단)` 을 돌려주고 값이 `None` 이면 **측정 실패**다.
측정 실패는 통과가 아니다 — 게이트가 거부로 처리한다.

#### 테스트가 하나도 없는 프로젝트

게이트는 "기능 ID 를 인용하는 통과 테스트"를 요구하므로 **모든 기능을 거부한다.**
설계대로 동작하는 것이지만 쓸 수는 없다. `inspect` 가 막는 것을 전부 열거한다.

```
→ 붙기 전에 해결할 것 3건:
   1. 런너(vitest)를 실행할 수 없습니다. npm install -D vitest 로 추가하십시오.
   2. 테스트 파일이 0개입니다. ... 지금 붙이면 모든 기능이 거부됩니다
   3. 명세(features.json)가 없습니다. 이것이 사람이 채워야 하는 유일한 입력입니다
```

### 4.4 의도 없이 판정되는 것 — `inspect`

> *"내가 테스트를 정의해야 한다는 거야? 프로젝트를 검수해서 객관적 평가 지표를
> 세팅할 수 없어?"*

절반은 가능하다. 경계가 어디인지가 중요하다.

| | 무엇인가 | 누가 정하나 |
|---|---|---|
| **명세** (`features.json`) | "무엇이 되어야 하는가" = **의도** | 사람 |
| **불변식** | 코드 안의 **두 지점이 어긋나는가** | 기계 |

**순환과 불변식은 다르다.** 이 구분이 이 프로젝트에서 가장 비싸게 배운 것이다(TS-013).

- 순환 — 구현 A 를 읽어 명세를 쓰고 구현 A 를 검사한다. 항상 통과한다. 무의미.
- 불변식 — 선언 D 와 구현 I 의 **일치**를 본다. 둘 중 하나가 틀리면 잡힌다.

`routes.ts` 의 `PROTECTED_PATHS` 와 `App.tsx` 의 라우트 등록은 **서로 다른 두 지점**이다.
"선언된 경로가 모두 등록되는가"는 코드에서 추출했지만 순환이 아니다 —
판정에 "무엇이 보호되어야 하는가"라는 의도가 필요하지 않다.

`inspect` 는 둘을 나눠 보고한다.

**자동 판정** (`auto=True`, 종료 코드 1 로 차단 가능)

| 검사 | 선언 ↔ 구현 |
|---|---|
| `dead-script` | npm scripts ↔ dependencies (TS-012 재현) |
| `route-completeness` | 경로 목록 상수 ↔ 라우터 등록 |
| `untested-source` | 소스 디렉터리 ↔ 테스트의 import (커버리지 0 확정) |
| `unreferenced-export` | export ↔ 프로젝트 전체 import |

**의도 필요** (`auto=False`, 후보로만 제시 — 종료 코드에 영향 없음)

| 후보 | 왜 기계가 못 정하나 |
|---|---|
| `form-rules` | 폼이 있다. **무엇을 거부해야 하는가**는 코드에 적혀 있지 않다 |
| `error-path` | `await` 에 오류 분기가 없다. 실패 시 무엇을 보일지는 의도다 |

```bash
python -m harness.cli inspect --write-draft   # features.draft.json 생성
```

초안은 **`features.json` 에 직접 쓰지 않는다.** 쓰면 하네스가 자기가 코드에서 뽑은
명세로 그 코드를 검사하게 되어 순환이다. 각 항목에 `origin` 과 `needs_review` 가 박혀
출처를 지운 채 섞이지 않는다.

#### 정적 분석의 한계를 명시한다

검수를 처음 돌렸을 때 위반 4건 중 **2건이 오탐**이었다(둘 다 수정). 이 프로젝트는
돌연변이 점수에서 이미 같은 결론에 도달했다 — **오해를 부르는 수치는 없는 수치보다 나쁘다.**

- `.map()` 으로 생성된 라우트를 "누락"으로 봤다 → 목록을 순회하면 누락이 **구조적으로
  불가능**하므로 통과. 리터럴과 변수가 섞이면 **판정을 보류**한다.
- `/login` 이 `PROTECTED_PATHS` 에 없는 것을 위반으로 봤다 → 역방향에는 근거가 없다.
  경로 목록은 보통 부분집합이다. 역방향 검사를 삭제했다.
- `import { type ProtectedPath }` 의 인라인 `type` 을 떼지 않아 미참조로 봤다 → 수정.

---

### 4.5 증거의 출처 — 독립성 (TS-020)

```bash
python -m harness.cli independence
```

증거 사다리는 두 칸에서 멈춰 있었다.

```
이름 (TS-008)  →  소스 실행 (TS-016)  →  [빈칸]
```

빈 칸이 돌연변이라고 생각했지만 아니다. 돌연변이는 **같은 채널의 깊이**를 재고,
TS-013 이 드러낸 것은 **채널의 독립성**이었다. F-005 는 jest 51/51 녹색에 게이트
통과였지만 실 브라우저에서 동작하지 않았다 — 테스트가 `<Route path="/dashboard">` 를
**직접 만들어** 감쌌기 때문이다. 테스트가 검증 대상의 구조를 공급하면 그 구조는
검증되지 않는다.

TS-013 의 수정은 `routes.ts` 로 **F-005 하나만** 고쳤다. 정책은 바뀌지 않았다.
이 명령이 그 정책이다.

**두 가지 사실을 센다 — 점수가 없다.**

| 사실 | 질문 |
|---|---|
| 자급 | 앱이 선언한 컬렉션을 **import 해서 순회**하는가, 멤버를 **직접 적는가** |
| 채널 수 | 단위·E2E 중 몇 개가 이 기능을 태그하는가 |

```
AppRoutes.test.tsx       PROTECTED_PATHS import → .map    → 선언을 읽는다
ProtectedRoute.test.tsx  import 없음 + '/', '/dashboard'  → 자급
```

**심각도를 나눈다.** 첫 구현은 둘을 같은 등급으로 보고했는데 성격이 전혀 달랐다.

| 심각도 | 조건 | 의미 |
|---|---|---|
| `enumerated` | 멤버 2개 이상 | 컬렉션을 손으로 재현. 등급을 끌어내린다 |
| `hard-coded` | 멤버 1개 | `toHaveBeenCalledWith('/profile')` 류 기대값 단정. 약한 결합으로만 기록 |

경계를 2로 둔 근거는 **'집합을 열거한다'와 '원소 하나를 지목한다'를 가르는 최솟값**이다.
점수가 아니라 개수이며, 원본 리터럴을 함께 출력해 사람이 확인할 수 있다.

**등급은 두 사실을 합치지 않고 조합한다** — '선언을 읽는다'와 '두 채널이 교차 검증한다'는
다른 것이다.

| 등급 | 조건 |
|---|---|
| `cross-checked` | 채널 2개 |
| `single-channel` | 채널 1개, 컬렉션 재현 없음 |
| `self-supplied` | 컬렉션 재현 + 채널 1개 ← **TS-013 의 모양** |

**첫 측정** (통과 기능 6건):

```
교차검증 5 · 단일채널 1 · 자급 0
자급 사건: 컬렉션 재현 1건 · 약한 결합 1건

[단일채널] F-018   단위 1 / E2E 0  ← 교차 확인하는 채널이 없다
[교차검증] F-005   단위 2 / E2E 1  ← ProtectedRoute.test.tsx 가 /, /dashboard 열거
```

검사기가 **하드코딩 없이 TS-013 의 바로 그 파일을 찾아냈다.**

**게이트가 아니다.** 종료 코드는 항상 0 이다. 자급이 곧 결함은 아니고 — 단위 테스트가
픽스처를 만드는 것은 정상이다 — 문제는 그것이 **유일한 증거**일 때다. 통과/탈락으로
가르려면 "채널 몇 개면 충분한가"를 정해야 하고 그것은 `EVAL_WEIGHTS` 와 같은 근거 없는
상수가 된다. 수치를 먼저 쌓는다.

남는 구멍도 적어 둔다: `<Route path="/dashboard">` 를 **하나만** 손으로 쓴 테스트는
`hard-coded` 로 분류되어 등급을 내리지 않는다. 그걸 잡으려면 리터럴의 **구문 위치**를
봐야 하고 그것은 라우팅 전용 휴리스틱이 되어 생태계 중립성을 깬다.

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

### 6.1 게이트가 무엇을 걸렀는가 (TS-015)

토큰 없는 모드에서 측정할 것은 **비용이 아니라 판정의 효과**다. `cli` 가 판정마다 남기는
기록을 집계해 네 가지를 센다.

| 지표 | 의미 |
|---|---|
| 판정 분포 (통과/거부/회수) | 게이트가 얼마나 거부하는가 |
| 거부 사유 분포 | **세션이 주로 무엇을 빠뜨리는가** |
| 기능별 거부 횟수 | 하나를 입증하는 데 몇 번 막혔는가 |
| **회수(unmark) 횟수** | **게이트가 틀렸던 횟수** — 통과시킨 뒤 번복한 사건 |

마지막 지표가 핵심이다. 현재 유일한 데이터 포인트는 부끄러운 것이다 — F-005 에서
게이트는 **통과시켰고** 실제로 잡은 것은 E2E 였다(TS-013). 그 사건이 수치로 남는다.

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
| `HARNESS_REQUIRE_MUTATION_EVIDENCE` | `false` | 돌연변이 게이트 — 잡음 1건 이상 요구 (기능당 약 27초, TS-021) |
| `HARNESS_EVIDENCE_LEVEL` | `feature` | `suite` / `feature` / `step` |
| `HARNESS_PERSISTENT` / `DATABASE_URL` | `false` / (없음) | 체크포인터 영속화 (아래 주의) |
| `HARNESS_MEMORY_DIR` | `./.harness_memory` | 에피소드 메모리 경로 |

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
| `.harness.json` | O | 런너·대상·규약 선언. 없으면 기본값 = 외부화 이전 하드코딩 (TS-017) |
| `web_target/features.json` | O | 기능 75개 + `passes` + `verification` 증거 — **진실의 원천** |
| `features.draft.json` | X | `inspect --write-draft` 산출물. **명세가 아니다** — 사람이 옮겨야 효력 |
| `web_target/src/routes.ts` | O | 보호 경로 목록의 단일 출처 (앱과 테스트가 공유, TS-013) |
| `troubleshooting/` | O | 실패 모드 22건 + `evidence/` 1차 자료 |
| `.harness_memory/<session>/` | O | Reflexion 반성 기록. 같은 세션 ID 로 재실행 시 주입된다 |
| `.claude/skills/harness/` | O | 토큰 없는 모드의 절차 |
| `harness_runtime.log` | X | 나이트 시프트 출력. `cli report` 의 입력 데이터 |

---

## 10. 현재 상태

```
기능 6/75 통과 — 전부 증거 기록 보유
jest 51/51 (7 suites) · E2E 14 통과 / 4 보류 / 실패 0
lint exit 0 · build exit 0 · tsc 오류 0
하네스 회귀 617건 (verification/repro_ts005/…/022) 전부 통과
자기 감사: 죽은 설정 0 · 고아 코드 0 · 미사용 임포트 0
유료 경로 스모크 78건 — LangGraph 그래프를 토큰 0 으로 끝까지 실행
다른 프로젝트 실측: main_portfolio(Vite, 테스트 0개) 검수 통과 — 막는 사유 3건 정확히 보고
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
python verification/repro_ts005.py   # LLM 오류 분류·백오프·종료 코드      37/37
python verification/repro_ts006.py   # 증거 게이트 정책                    32/32
python verification/repro_ts008.py   # 명세-테스트 연결 판정               49/49
python verification/repro_ts009.py   # 측정 계층 + 종료 상태 기록          36/36
python verification/repro_ts010.py   # 토큰 없는 모드 의존성 독립          22/22
python verification/repro_ts015.py   # 실행 기록 + 게이트 판정 집계        29/29
python verification/repro_ts016.py   # 커버리지 게이트 + 돌연변이 측정      31/31
python verification/repro_ts017.py   # 설정 외부화·런너 추상화·검수          90/90
python verification/repro_ts018.py   # 유료 경로 스모크 (LangGraph, 토큰 0)   78/78
python verification/repro_ts019.py   # 죽은 설정·고아 코드 재발 방지          37/37
python verification/repro_ts020.py   # 증거 독립성 (자급 판정·채널 수)        50/50
python verification/repro_ts021.py   # 변이 연산자 + 돌연변이 게이트          58/58
python verification/repro_ts022.py   # 탐지 범위 (표본·컬렉션 연산자)        68/68

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
- **하네스 유무의 A/B 를 돌리지 못했다** — §6 은 *게이트 기준*의 A/B 이고, 하네스 전체의
  효과는 미측정이다. 설계는 서 있으나 수치가 없다.
- 게이트 판정 집계(§6.1)는 이제 쌓이기 시작했을 뿐이다 — 표본이 적다.
- 유료 경로는 **스모크 테스트로 고정했지만**(TS-018) 실제 LLM 과 끝까지 돌린 것은
  2026-04-14 이 마지막이다. 스텁은 배선·라우팅·종료 코드를 보장하고, 프롬프트 품질과
  실제 모델 거동은 보장하지 않는다.
  남은 커버리지 공백: `tools.py` 15% (도구 12개 중 일부만 실행), `memory.py` 18%.
- Evaluator 의 LLM 채점과 `EVAL_WEIGHTS` / 75점 임계는 **근거 없는 상수**다.
  단, `features.json` 의 플래그는 그 점수에 의존하지 않는다 — 분리되어 있다.
- 태그된 테스트가 **제대로** 검증하는지는 게이트가 완전히 보지 못한다.
  커버리지 요구로 공허한 테스트는 막았지만(TS-016), 실행하면서 단정하지 않는 테스트는
  돌연변이 측정으로만 드러나고 그것은 게이트가 아니다 (느려서).
- 커버리지 임계 80% 대비 실측 미달.
- **`cli deadcode` 는 정적 분석이다.** `eval`·`importlib` 동적 참조는 보지 못한다.
  이 레포에 그런 참조가 없음을 확인했기에 CI 에서 차단으로 쓴다 — 다른 프로젝트에서는
  보고로만 쓸 것.
- **Reflexion 의 프롬프트 품질은 미검증이다.** TS-018 이 "오류 신호가 프롬프트에 들어간다"는
  것까지 고정했을 뿐, 그 반성이 유용한지는 실제 모델로 돌려봐야 안다 (F-004 증거 참조).
- **`inspect` 는 정적 분석이다.** 재export·동적 import·리플렉션을 보지 못한다.
  오탐 3건을 실측으로 잡아 고쳤지만(TS-017), 같은 종류가 더 있을 수 있다 —
  자동 판정 결과는 차단 근거로 쓰기 전에 한 번 눈으로 확인할 것.
- **pytest 의 커버리지는 `pytest-cov` 가 필요하다.** 없으면 측정 실패 → 게이트가
  거부한다(설계대로). 설치 안내는 진단 메시지에 들어 있다.
- vitest·pytest 어댑터는 **단위 검증으로만 확인했다** — 실제 vitest/pytest 프로젝트에서
  끝까지 돌려본 것은 아니다. jest 경로만 실 환경 검증(51/51)을 거쳤다.

---

## 10.1 CI

매 푸시마다 GitHub Actions 가 **선언된 모든 명령을 실제로 돌린다** — 이 프로젝트가
네 번 반복한 "선언했는데 아무도 돌려보지 않아 유지된 결함"에 대한 기계적 처방이다.
토큰 없는 모드이므로 **API 키 없이 전부 돈다**(비용 0).

| 잡 | 내용 |
|---|---|
| `하네스 검증` | `verification/repro_ts005/…/022` (617건) + `cli deadcode` + `cli tags` + `cli independence` + `cli inspect` + `cli audit` + `cli report` |
| `대상 앱` | `tsc --noEmit` · `npm run lint` · `npm run build` · `npx jest . --no-coverage` |
| `E2E` | `npx playwright install chromium webkit` + `npm run test:e2e` (실패 시 리포트 업로드) |

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
| TS-015 | 토큰 없는 모드로 옮기며 측정 계층의 절반이 고아가 됐다 — 기록자가 사라진 것을 몰랐다 |
| TS-016 | 아무것도 실행하지 않는 테스트가 완벽한 증거로 계수됐다 — 커버리지 게이트와 돌연변이 측정 |
| TS-017 | 하네스가 레포 한 곳에만 붙어 있었다 — 설정 외부화·런너 추상화·프로젝트 검수 |
| TS-018 | 유료 경로가 6개월간 검증 없이 방치됐다 — 스모크 테스트가 즉시 버그 2건을 찾아냈다 |
| TS-019 | 문서가 광고하는 설정 3개가 아무 일도 하지 않았다 — 죽은 설정의 두 번째 재발 + 고아 코드 21건 |
| TS-020 | 증거 사다리의 빈 칸은 깊이가 아니라 독립성이었다 — TS-013 을 정책으로 일반화 |
| TS-021 | 변이 연산자가 테스트를 시험하지 않고 컴파일러를 시험했다 — 190곳 중 3곳만 진짜 비교 |
| TS-022 | 탐지가 닿지 않는 두 구멍 — 표본은 파일 앞머리만, 연산자는 배열을 못 건드렸다 |

전체 목록: [troubleshooting/INDEX.md](troubleshooting/INDEX.md)

**반복된 패턴**: "선언과 실제의 불일치가 실행되지 않아 유지된다" — 네 번 나왔다
(TS-001 루트 `features.json`, `init.sh` 의 `PROJECT_ROOT`, TS-006 의 `run_tests`, TS-012 의 3건).
하위 디렉터리로 프로젝트를 옮긴 뒤 루트에 남은 설정 파일을 전수 점검하지 않은 결과다.

---

## 12. 참고

- 외부 프로젝트 비교 분석과 기준의 근거: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)
- Reflexion 이 오류 신호 없이 근본 원인을 날조한 1차 증거:
  [troubleshooting/evidence/F-004-reflexion-confabulation/](troubleshooting/evidence/F-004-reflexion-confabulation/)

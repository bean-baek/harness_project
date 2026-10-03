---
id: TS-010
title: 하네스의 가치는 이미 토큰을 쓰지 않았다 — 유료 API를 추론 엔진에서 제거
date: 2026-10-01
category: architecture
severity: high
status: resolved
component: harness/cli.py
tags: [cost, tokenless, claude-code, skill, enforcement, dependency-isolation]
guard: 토큰 없는 경로가 표준 라이브러리만 쓴다 — repro_ts010 이 import 를 고정한다
exposure: tokenless-isolation
---

## Symptoms
- Gemini 프로젝트가 월 지출 한도를 소진했고(TS-005), 그 대가로 통과한 기능은 **5/75** 였다.
  그 5건마저 자율 실행의 결과가 아니라 사람과 결정론적 도구가 교정한 것이다.
- 즉 **비용은 전액 지불되었고 자율 구현 성과는 0에 가까웠다.**
- "그 비용이 실제로 필요했는가"라는 질문에 답할 데이터가 없다 — 기능당 토큰도 기록하지 않았다.

## Root cause
하네스 코드를 성격별로 세어보면 결론이 분명하다.

| 성격 | 줄 수 | 토큰 |
|---|---|---|
| 결정론적 기계 — 증거 게이트, 측정, 도구, 라우팅, 상태, 메모리 | **2,060** | **0** |
| 유료 LLM API를 돌리기 위한 코드 — 에이전트 노드, 오류 분류, 그래프, 프롬프트, 진입점 | 2,357 | 전량 |

**가치 있는 쪽은 이미 무료였다.** TS-004~009 에서 만든 것들(silent-abort 가드,
종료 코드 규약, 증거 게이트, 명세-테스트 연결, 판별력 측정)은 단 한 번도 LLM을 호출하지 않는다.
유료 API가 맡은 역할은 **'추론 엔진'** 하나였고, 그 역할은 이미 구독으로 비용을 낸
Claude Code 세션이 대신할 수 있다.

구조적 결합도 있었다: `harness/__init__.py` 가 `state` / `graph` 를 즉시 임포트해
`import harness.verify` 만 해도 langchain·langgraph 가 끌려왔다. 무료 경로가 유료 스택에
묶여 있어 분리 가능성이 보이지 않았다.

## 왜 마크다운만으로 가지 않았는가
[revfactory/harness](https://github.com/revfactory/harness) 는 실행 코드 0줄의 순수 마크다운
플러그인이고, 그래서 자체 API 비용이 0이다. 그 방향을 그대로 따르면 **강제력을 잃는다.**

TS-006 의 교훈이 정확히 그것이다 — `update_features` 의 "테스트를 먼저 실행하십시오"가
docstring 안의 **권고**였을 때 에이전트는 무시하고 자가 채점했고, 75개 기능 중 어느 것이든
통과로 기록할 수 있는 상태였다(판별력 측정: `suite` 수준 100% 통과, TS-008).
마크다운은 권고만 할 수 있다. 판정은 코드여야 한다.

그래서 **절차는 마크다운, 판정은 파이썬**으로 나눴다.

## Fix
- **[harness/cli.py](../harness/cli.py) (신설)** — 토큰을 쓰지 않는 하네스 진입점.
  `next` / `show` / `verify` / `mark` / `unmark` / `audit` / `report`.
  종료 코드 규약: **0 통과, 1 거부, 2 입력 오류**.
  `--project` 는 서브명령 전후 모두 허용한다(공통 부모 파서).
- **[.claude/skills/harness/SKILL.md](../.claude/skills/harness/SKILL.md) (신설)** —
  세션이 따를 절차. 네 가지 불신, 태그 규약, 거부 사유별 대처, 금지 사항
  (`features.json` 직접 편집 / 게이트 비활성화 / `main.py`·`night_shift.py` 실행).
- **[harness/verify.py](../harness/verify.py)** — 게이트 정책(`apply_flag`)을 이 모듈로 이관.
  `load_features` / `save_features` / `find_index` 추가.
  **구현은 하나뿐이다** — langchain 도구 `update_features` 는 이제 `apply_flag` 위임 3줄이다.
  CLI 와 도구가 같은 판정을 내리는 것이 보장된다(검증 §4).
- **[harness/__init__.py](../harness/__init__.py)** — PEP 562 `__getattr__` 지연 로딩.
  `from harness import build_harness_graph` 는 그대로 동작하고,
  `harness.verify` / `metrics` / `cli` 는 langchain 없이 임포트된다.
- **[config.py](../config.py)** — `python-dotenv` 를 선택 의존성으로. 없으면 no-op.

### 역할 대응
| 기존 (유료) | 토큰 없는 모드 |
|---|---|
| P-01 Orchestrator | `cli next` — 다음 기능과 태그 규약 출력 |
| P-03 Coder (Gemini) | **Claude Code 세션** (구독 비용에 포함) |
| P-04 Evaluator (Gemini) | `cli verify` (결정론적) + 선택적으로 서브에이전트 독립 검토 |
| P-05 Reflector | 세션의 컨텍스트 + `troubleshooting/` 기록 |
| `night_shift.py` 무인 루프 | **없다** — 가장 큰 손실 (아래) |

## Verification
`repro_ts010.py` — **22/22 PASS**. 실제 LLM 호출 없음.

- **의존성 독립 6건**: `langchain` / `langchain_core` / `langchain_google_genai` /
  `langgraph` / `dotenv` / `google` 을 메타 임포트 훅으로 **전부 차단**하고 `GOOGLE_API_KEY=""`
  로 둔 서브프로세스에서 `harness.verify` / `metrics` / `cli` / `config` 임포트 성공.
  **대조군**으로 `harness.tools` 와 `harness.graph` 는 차단되어 실패하는 것까지 확인
  (차단이 실제로 작동함을 증명).
- **차단 상태 판정 5건**: F-004 통과(종료 0, 근거 테스트 출력), F-005 거부(종료 1, 사유 제시),
  없는 ID(종료 2).
- **플래그 불변성 2건**: `mark` 거부 시 `features.json` 바이트 단위 무변경.
- **단일 구현 6건**: 같은 상황에서 CLI(`apply_flag`)와 langchain 도구(`update_features`)의
  **메시지가 문자 단위로 동일**하고, 기록된 증거 블록도 타임스탬프 외 전부 동일.
  거부 메시지도 동일.
- **지연 로딩 2건**: `import harness.verify` 후 `sys.modules` 에 `langchain_core` 와
  `langgraph` 가 **없음**. 재export 는 `dir(harness)` 에 여전히 노출.

회귀: `repro_ts005` 37/37, `repro_ts006` 32/32, `repro_ts008` 49/49, `repro_ts009` 36/36,
대상 앱 jest 27/27. 유료 경로(`main.py`, `night_shift.py`, `graph.py`)도 임포트 정상 —
**삭제하지 않고 남겨뒀다**(무인 실행이 필요해지면 쓸 수 있어야 한다).

## 무엇을 잃는가 (정직하게)
1. **무인 야간 실행이 사라진다.** `night_shift.py` 는 30분 타임아웃으로 기능을 연속 정복하는
   루프였다. Claude Code 세션은 사람이 열어둔 동안만 돈다. 자율성이 떨어진다 —
   "자는 동안 유료 키로 돌리기"를 "깨어 있는 동안 구독으로 돌리기"와 교환한 것이다.
2. **비용이 사라지는 게 아니라 이동한다.** 구독 사용량/속도 제한으로 옮겨가고,
   기능당 비용은 여전히 측정되지 않는다 (미해결 격차).
3. **모델을 나눌 수 없다.** 구현자와 채점자에 서로 다른 모델을 쓰는 설계는 포기한다
   (서브에이전트로 역할 분리는 가능하지만 같은 모델 계열이다).
4. **채점자 편향이 남는다.** 구현한 세션이 자기 작업을 보게 된다. 다만 `features.json`
   플래그는 LLM 판단이 아니라 jest 결과로 결정되므로, 편향의 영향 범위가 좁다.

## Prevention
- **비용 구조를 먼저 세어볼 것.** "토큰이 필요한 부분"과 "이미 무료인 부분"을 줄 수로
  분리하면 설계 선택지가 드러난다. 이 프로젝트는 그 계산을 9개 TS 문서를 쓴 뒤에야 했다.
- **강제는 코드로, 절차는 문서로.** 문서에 적힌 규칙은 지켜지지 않는다(TS-006).
  반대로 모든 것을 코드로 만들면 유연성을 잃는다. 경계는 "판정이냐 안내냐"에 있다.
- **정책 구현을 한 곳에만 둘 것.** 같은 게이트를 CLI와 도구가 각자 구현하면 조용히 갈라진다.
  `apply_flag` 하나를 양쪽이 호출하고, 그 동일성을 테스트로 고정했다.
- **패키지 `__init__.py` 에 무거운 임포트를 두지 말 것.** 가벼운 모듈 하나를 쓰려는
  사용자가 전체 의존성 스택을 끌어오게 된다. 지연 로딩(PEP 562)으로 해결된다.
- **"의존성이 없다"는 주장은 차단 테스트로 증명할 것.** 임포트 훅으로 막고 돌려보면
  숨은 결합이 드러난다 — 실제로 `harness/__init__.py` 가 그렇게 발견됐다.

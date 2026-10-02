---
id: TS-019
title: 문서가 광고하는 설정 3개가 아무 일도 하지 않았다 — 죽은 설정의 두 번째 재발 + 고아 코드 21건
date: 2026-10-02
category: maintenance
severity: medium
status: resolved
component: harness/deadcode.py, harness/router.py, config.py
tags: [dead-config, orphan-code, self-audit, recurrence, static-analysis]
---

## Symptoms
사용자가 폴더·파일 정리와 고아 코드 점검을 요청했다. 눈으로 훑지 않고 AST 로
정의와 참조를 교차해 셌다. 두 종류가 나왔다.

### 1. 죽은 설정 — README 가 광고하지만 코드가 읽지 않는다

| 환경변수 | README 설명 | 실제 |
|---|---|---|
| `HARNESS_EVAL_THRESHOLD` | "Evaluator 합격선" (기본 75) | `config.EVAL_PASS_THRESHOLD` 를 **아무도 읽지 않는다.** `route_after_evaluate` 가 `score >= 75` 로 하드코딩 |
| `DEV_PORT` | "개발 서버 포트" | 읽는 코드가 없다 |
| `API_PORT` | "개발 서버 포트" | 읽는 코드가 없다 |

**`HARNESS_EVAL_THRESHOLD=90` 으로 설정하고 돌려도 합격선은 75였다.**
문서는 손잡이가 있다고 말하는데 돌려도 아무 일이 없다.

이것은 **TS-007 과 같은 양식의 두 번째 사례**다. TS-007 에서는
`HARNESS_PERSISTENT` / `DATABASE_URL` 이 그래프 빌더에 전달되지 않아 설정을 켜도
항상 `InMemorySaver` 였다. 같은 실패가 다른 설정에서 다시 났다.

### 2. 고아 코드 21건

| 위치 | 항목 | 성격 |
|---|---|---|
| `harness/memory.py` | `load_session_history`, `clear_session_memory`, `compress_context`, `read_progress_log`, `write_progress_log` | 호출 0건 |
| `harness/router.py` | `all_features_done` | 호출 0건 |
| `harness/tools.py` | `EVALUATOR_TOOLS`, `REFLECTOR_TOOLS` | 어떤 에이전트에도 바인딩 0건 |
| `harness/prompts.py` | `P16_CONTEXT_COMPRESS`, `P18_LANGGRAPH_ROUTER`, `P19_AUTOGEN_MANAGER`, `TOOL_DESCRIPTIONS` | 구현된 적 없는 기능의 프롬프트 |
| `config.py` | `WEB_TARGET_DIR`, `MAX_SESSIONS`, `CONTEXT_THRESHOLD`, `DEV_PORT`, `API_PORT`, `DEV_URL`, `API_URL` | 참조 0건 |
| `harness/tags.py` | `_ID_RE`, `_DESCRIBE_RE` | **TS-017 에서 "하위 호환"이라며 남겼지만 아무도 쓰지 않았다** |

마지막 줄이 특히 나쁘다. 바로 전 커밋에서 내가 "재현 스크립트가 쓸 수 있으니 남긴다"고
주석까지 달아 보존했는데, 실제로는 어느 스크립트도 참조하지 않았다.
**보존의 근거를 확인하지 않고 보존했다.**

또 `EVALUATOR_TOOLS` 는 **설계와 모순**이다. `evaluator_node` 는
"Coder 가 남긴 ToolMessage 히스토리만 보고 채점"하도록 도구를 바인딩하지 않으며
그 사실이 코드 주석과 README 에 명시돼 있다. 쓰지 않을 도구 목록이 남아 있으면
다음 사람이 바인딩해야 하는 줄 안다.

그리고 `compress_context` + `CONTEXT_THRESHOLD` + `P16_CONTEXT_COMPRESS` 는
한 묶음으로, **구현된 적 없는 '문맥 압축' 기능의 잔해**였다. 세 조각이 서로를
참조하지 않고 각각 떠 있어 어느 하나만 보면 "쓰이는 것 같다"고 착각하게 된다.

## Root cause
- **설정을 추가할 때 읽는 쪽을 만들지 않아도 아무도 모른다.** `config.py` 에 상수를
  쓰고 README 에 한 줄 적으면 "기능이 있다"는 외관이 완성된다. 실제 소비 지점이
  없다는 사실은 그 설정을 실제로 바꿔볼 때만 드러나고, 아무도 바꿔보지 않는다.
- **리팩터는 삭제보다 보존을 선호한다.** "하위 호환을 위해 남긴다"는 판단이 맞는지
  확인하는 비용(grep 한 번)을 지불하지 않으면 그 보존은 영구적인 고아가 된다.
- 두 번 반복된 패턴은 **사람의 기억으로 막을 수 없다.** 기계가 세야 한다.

## Fix
### 1. 죽은 손잡이 2개를 연결했다 (삭제가 아니라 작동시킴)
- `router.route_after_evaluate` → `score >= config.EVAL_PASS_THRESHOLD`
  (하드코딩 `75` 제거). 이제 `HARNESS_EVAL_THRESHOLD` 가 실제로 판정을 바꾼다.
- `agents._get_llm` → `max_tokens=config.LLM_MAX_TOKENS`
  (하드코딩 `4096` 제거). 비용 상한을 환경변수로 조절할 수 있게 됐다.

손잡이가 문서화돼 있으면 **삭제보다 연결이 맞다.** 사용자가 기대하는 기능을
없애는 대신 기대대로 동작하게 만든다.

### 2. 진짜 고아는 삭제했다 (21건 + 미사용 임포트 14건)
`DEV_PORT`/`API_PORT`/`DEV_URL`/`API_URL` 은 **연결할 소비 지점이 없다** —
하네스에 개발 서버를 띄우는 코드가 아예 없다. 문서에서도 제거했다.
문서와 코드 중 하나를 고쳐야 할 때, **없는 기능은 문서에서 내리는 것**이 맞다.

### 3. 기계적 가드 — `harness/deadcode.py`
세 검사를 구현했다. 전부 **'참조 0건'이라는 사실 판정**이고 임계값이 없다.

| 검사 | 무엇을 보는가 |
|---|---|
| `find_dead_config` | 문서가 광고하는 환경변수인데 그 상수를 아무도 읽지 않는다 |
| `find_orphans` | 정의됐지만 **정의 외** 참조가 0건인 최상위 심볼 |
| `find_unused_imports` | 임포트했지만 그 파일에서 쓰지 않는 이름 |

`python -m harness.cli deadcode` 로 실행하고 발견 시 종료 코드 1 을 낸다.
CI 가 차단으로 쓴다.

**오탐 방어** (TS-017 의 교훈 — 오탐을 내는 검사는 없는 검사보다 나쁘다):
- 참조를 `Name`·`Attribute`·`alias`·**문자열 리터럴**에서 모두 수집한다.
  문자열까지 보는 이유: LangGraph 노드는 `add_node("done", fn)` 으로 등록되고
  `getattr(mod, "name")` 패턴도 있다.
- **정의 줄 자신의 Store 는 참조로 세지 않는다.** 이걸 빠뜨린 첫 구현에서
  CLI 명령 11개와 그래프 노드 3개가 '미사용'으로 나왔다
  (`set_defaults(func=cmd_next)` 는 같은 파일 안의 정당한 참조다).
- 미사용 임포트는 **단어 경계**로 찾는다. 부분 문자열로 찾으면 `import io` 가
  `'revision'` 안의 `io` 때문에 '사용 중'으로 보인다 — 실제로 첫 구현이 그래서
  7건을 놓쳤다.
- `from __future__ import annotations` 는 면제한다. 컴파일러 지시자이므로
  이름으로는 영원히 미사용이다.
- `main`·던더는 프레임워크가 호출하므로 면제한다.

## Verification
`repro_ts019.py` — **37/37 PASS**.

**검사기 자신이 작동하는지를 먼저 본다** (TS-016 의 교훈: "0건"은 감사가 아무것도
못 찾는 상태와 구별되지 않는다). 각 검사기에 **일부러 결함을 심은 임시 프로젝트**를
주고 잡는지 확인한 뒤, 실제 레포가 0건임을 단정한다.

- 고아 탐지 5건 — 미호출 함수·상수·클래스를 잡고, 다른 파일에서 쓰이는 것은 안 잡는다
- **오탐 방어 4건** — 같은 파일 참조, 그래프 노드 인자 전달, `getattr` 문자열 참조
- 면제 3건 — `main`, 던더, `annotations`
- 미사용 임포트 4건 — 부분 문자열 오탐(`io` vs `'revision'`) 포함
- 죽은 설정 6건 — 문서화된 것만 잡고, env 를 읽지 않는 평범한 상수는 제외
- 감사 범위 5건 — `web_target`·`.venv`·`node_modules` 제외
- **이 레포가 깨끗한가 3건** — 죽은 설정 0 / 고아 0 / 미사용 임포트 0
- **되살아난 손잡이 5건** — 임계값을 50 으로 낮추면 60점이 통과하고 95 로 올리면
  같은 60점이 거부된다. **설정을 바꾸면 판정이 실제로 바뀐다**는 것이
  '죽은 설정이 아니다'의 증거다
- CLI 노출 2건

**실 환경**
- 삭제 후 하네스 회귀 **441건**(기존 404 + TS-019 37) 전부 통과.
  TS-018 의 스모크 테스트가 유료 경로 삭제의 안전을 입증했다 — 그것이 없었다면
  `tools.py`/`prompts.py`/`memory.py`/`router.py` 에서 21건을 지운 뒤
  "아마 괜찮을 것"이라고 말할 수밖에 없었다.
- 게이트 6/6, jest 51/51, tsc 0, `cli deadcode` 종료 코드 0
- **가드가 자기를 작성한 파일을 즉시 잡았다** — `repro_ts019.py` 의 미사용
  `import json` 을 첫 실행에서 보고했다

## Prevention
- **설정을 추가할 때 소비 지점을 같은 커밋에 넣을 것.** 상수만 추가하고 읽는 쪽을
  나중에 하면 그 '나중'은 오지 않는다.
- **문서화된 손잡이는 삭제보다 연결.** 없는 기능은 문서에서 내리고,
  있어야 하는 기능은 동작하게 만든다. 둘 중 하나는 반드시 한다.
- **"하위 호환을 위해 남긴다"를 주석으로 쓸 때 grep 으로 확인할 것.**
  확인하지 않은 보존은 영구적인 고아다 — 바로 전 커밋(TS-017)에서 내가 그랬다.
- **미사용 검사는 단어 경계로.** 부분 문자열 매칭은 '사용 중'을 과대 보고해
  검사를 무력화한다.
- **정의 줄 자신을 참조로 세지 말 것.** 세면 모든 것이 '사용 중'이 되고,
  세지 않으면 같은 파일 안의 정당한 참조가 '미사용'이 된다. 둘을 구분해야 한다.
- **두 번 반복된 실패는 기계에 맡길 것.** TS-007 이 한 번일 때는 기록으로 충분했고,
  TS-019 에서 두 번이 되자 가드가 필요해졌다.
- **고아 삭제의 안전은 스모크 테스트가 보장한다.** 검증되지 않는 코드에서 무언가를
  지우면 "아마 괜찮다"밖에 말할 수 없다 (TS-018).

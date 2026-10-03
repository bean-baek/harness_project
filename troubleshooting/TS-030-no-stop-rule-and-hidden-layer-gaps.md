---
id: TS-030
title: 계층별 지원 차이가 보이지 않았고, 도구 만들기를 멈출 사실 판정이 없었다
date: 2026-10-04
category: verification-design
severity: medium
status: resolved
component: harness/status.py, harness/exposure.py, docs/adding-a-language.md
tags: [language-support, stop-rule, loop, generated-file, recursion]
guard: 지원 계층 표를 `docs/status.md` 가 **코드에서 읽어 생성**하고, 각 실패 모드가 `resolution: build|use|accept` 를 선언해 `cli exposure` 가 "더 만들 것이 남았는가"를 사실로 답한다
exposure: language-matrix
resolution: accept
---

## Symptoms

두 질문에 답할 장치가 없었다. 둘 다 사용자가 물어서 드러났다.

### 1. "어떤 언어로 써도 동작하는가"

답은 **아니오**인데, 어디까지 되는지를 알려주는 것이 없었다. 측정해보니 계층마다
묶인 정도가 완전히 달랐다.

```
변이 연산자가 매칭되는 개수 (대표 구문 한 줄)
  jest    4곳
  vitest  4곳
  pytest  0곳   ← 돌연변이 측정이 파이썬에서 아무것도 하지 않는다
```

파이썬에는 `===` 도 `&&` 도 없고 `if` 에 괄호를 쓰지 않는다. **증거 사다리의 가장
강한 칸이 pytest 프로젝트에서는 비어 있다.** 그런데 README 는 "jest·vitest·pytest
지원"이라고만 적었다. 읽는 사람이 그 차이를 알 방법이 없었다.

### 2. "문제가 무한히 나와 혼자 루프를 도는가"

이 세션이 그 모양이었다 — TS-025(5건) → TS-026(1건+정정 4건) → TS-027(3건) →
TS-028(5건) → TS-029(2건). 고칠 때마다 더 나왔다.

하네스 자체는 루프를 만들지 않는다. 게이트는 전부 "0건이냐"를 묻는 끝나는 질문이고
임계값이 없어 "더 올려라"가 나올 수 없다. 루프를 만든 것은 **도구를 감사하는 쪽**이다.

문제는 **멈출 시점을 판정할 사실이 없었다는 것**이다. "이제 됐다"가 느낌이었다.

## Root cause

두 증상의 원인이 같다 — **하네스가 자기 상태를 말하지 못했다.**

TS-027 이 "실패 모드가 산문으로만 존재해서 읽는 사람이 대입해야 했다"를 고쳤다.
그런데 같은 문제가 두 군데 남아 있었다.

| | 산문에만 있던 것 | 결과 |
|---|---|---|
| 지원 계층 | README 의 "jest·vitest·pytest" | 계층 차이가 안 보임 |
| 멈출 시점 | 아무 데도 없음 | 판단이 느낌에 의존 |

## Fix

### 1. 지원 표를 **생성한다** — 손으로 적지 않는다

`docs/status.md` 에 `language_support()` 가 만든 표를 싣는다. `RUNNERS`·픽스처의
`.harness.json`·CI 워크플로·연산자 표를 **읽어서** 만들고, 변이 칸은 그 언어의 대표
구문에 연산자가 매칭되는 **실측 개수**다.

```
| 런너 | 피험체 | 게이트 | CI 실행 | 검수 | 컬렉션 | 초안 | 변이 |
|---|---|---|---|---|---|---|---|
| jest | web_target | O | O | O | O | O | 4곳 |
| pytest | pytest-app | O | — | O | O | — | 0곳 |
| vitest | vanilla-js | O | — | O | O | O | 4곳 |
```

손으로 적으면 계층이 늘 때 조용히 거짓이 된다 — 그것이 TS-024 다. `cli status --check`
가 드리프트를 막는다.

절차는 [docs/adding-a-language.md](../docs/adding-a-language.md) 에 썼다. 핵심은
**게이트만 넓히면 된다**는 것 — `Runner` 서브클래스 1개 + 픽스처 1개가 필수이고,
변이 연산자는 가장 비싸고 가장 안 정확하므로 선택이다.

### 2. 멈출 판정 — 각 실패 모드가 **무엇으로 해결되는지** 선언한다

TS 문서 frontmatter 에 한 칸을 더한다.

```yaml
resolution: build | use | accept
```

| | 뜻 |
|---|---|
| `build` | 도구를 더 만들어야 한다 |
| `use` | 도구는 됐고 **실제로 써봐야** 한다 (예: pytest 프로젝트에 붙여보기) |
| `accept` | 받아들이는 조건이다 (고칠 것이 없다) |

`cli exposure` 가 노출된 것을 이 셋으로 세어 출력한다.

```
노출된 것은 무엇으로 해결되는가
  더 만들어야 (build)  0건
  써봐야 (use)         0건
  받아들임 (accept)    1건  TS-017
  → **도구를 더 만들 이유가 없다.** 남은 것은 쓰거나 받아들이는 것이다
```

**임계값이 아니라 개수다.** `build` 가 0 이면 만들 이유가 없다는 **사실**이고, 내가
정한 숫자가 아니다. 선언은 문서에만 있고, `cli exposure` 가 `resolution` 이
세 값 중 하나가 아니면 종료 코드 1 로 차단한다.

### 3. 새 명령을 만들지 않았다

이 수정 자체가 "도구를 더 만들지 말라"는 규칙의 대상이므로, **기존 생성 파일과 기존
명령에만** 넣었다. `cli loop` 같은 것을 만들면 규칙을 규칙 위반으로 만든다.

## 만드는 중에 만든 결함 — **무한 재귀**

`status.collect` 에 `unresolved_by_building()` 을 넣었다. 그것이
`exposure.diagnose` 를 부르고, 그 안의 `check_published_numbers` 가 다시
`status.check` → `collect` 를 불렀다.

```
collect → diagnose → check_published_numbers → status.check → collect → ...
```

**루프를 끊는 규칙을 만들면서 무한 루프를 만들었다.** `cli exposure` 가 10분 넘게
돌지 않아서 발견했다.

그리고 중복이기도 했다 — `cli exposure` 의 출력이 이미 build/use/accept 를 센다.
같은 사실을 두 곳에서 계산하면 둘이 어긋날 수 있다(TS-024 의 모양). 함수를 지우고
`cli exposure` 한 곳에만 남겼다.

> **교훈**: 생성 파일은 **싼 측정만** 담는다. 다른 진단을 호출하는 측정은 생성 파일에
> 넣지 않는다 — 비용도 모르고 순환도 보이지 않는다. `status.py` 의 docstring 이
> 이미 "비싼 측정은 값을 발표하지 않는다"고 적고 있었는데, 비용이 **시간**이 아니라
> **호출 구조**일 수 있다는 것을 놓쳤다.

## 그 비용을 쫓다 더 큰 것을 찾았다 — 걷기를 자르지 않았다

재귀를 고친 뒤에도 `cli exposure` 가 22초, `repro_ts027` 이 **3분 42초**였다.
프로파일을 떠 보니 원인이 전혀 다른 곳이었다.

```
_test_files                  1.45초   ← 호출당. inspect 안에서 3번 불린다
assess_readiness             5.20초
deadcode.audit               5.60초
inspect_project (전체)       14.30초

node_modules 안의 항목 수: 17,721  (걷는 데 1.08초)
```

`Path.rglob("*")` 은 **`node_modules` 와 `.venv` 안까지 전부 걷고 나서** `SKIP_DIRS`
로 필터한다. 걸러질 파일을 먼저 다 걷는 것이다. `SKIP_DIRS` 는 "들어가지 말라"는
뜻으로 쓰려고 만든 것인데 **거르는 데만** 쓰고 있었다.

`os.walk` 는 `dirnames` 를 **제자리에서** 비우면 그 아래로 내려가지 않는다.
`project.walk_files()` 가 그것을 하고, 네 모듈이 그것을 쓴다.

```
                        전        후
_test_files           1.45초   0.00초
deadcode.audit        5.60초   0.52초
inspect_project      14.30초   1.33초
cli exposure         68.00초   7.75초
repro_ts027          3분42초   1분23초
```

**동작은 하나도 바뀌지 않았다** — 같은 파일 목록이 나온다. 검증 건수도 그대로다.
비용만 바뀌었다.

이것이 왜 TS-030 에 들어가는가: **검증이 느려지면 검증을 줄이는 압력이 생긴다.**
`repro_ts027` 이 3분 42초일 때 내 첫 반응은 "검사를 줄일까"였다. 그 압력이
TS-029 의 `|| true` 와 같은 모양이다 — 도구가 쓰기 불편해지면 사람이 도구를 끈다.
비용은 기능이 아니라 **채택의 조건**이다.

## Verification

```
python verification/repro_ts025.py     # 지원 표와 피험체 — 이식성 스크립트에 둔다
python -m harness.cli exposure         # resolution 선언 누락이면 종료 코드 1
python -m harness.cli status --check   # 지원 표 드리프트 차단
```

핵심 검사:

- 모든 런너에 피험체(픽스처 또는 주 대상)가 있는가 — 없으면 그 모양은 **한 번도
  검증된 적이 없다**
- 표가 **생성된 것인가** — 손으로 적은 값이 섞이면 `--check` 가 잡는다
- 모든 TS 가 `resolution` 을 `build`/`use`/`accept` 중 하나로 선언했는가
- `status.collect` 가 `exposure.diagnose` 를 **부르지 않는가** (재귀 방지)

## Lesson

**"됐다"는 느낌이 아니라 사실이어야 한다.**

이 프로젝트는 판정을 전부 사실로 만들었다 — 통과 플래그, 태그, 죽은 설정, 문서 드리프트.
그런데 **"이제 도구를 그만 만들어도 되는가"** 라는 가장 큰 판정이 느낌으로 남아 있었다.

그 판정을 사실로 바꾸는 방법은 임계값이 아니라 **분류**였다. 노출된 각 항목이
*만들어야 / 써봐야 / 받아들여야* 중 무엇인지는 그 항목을 쓴 사람이 안다. 세어 보면
0인지 아닌지가 나오고, 그것은 방어할 수 있는 사실이다.

그리고 이 수정 자체가 그 규칙에 걸렸다 — 재귀를 만든 것도, 새 명령을 만들지 않기로
한 것도 같은 이유다. **규칙을 만들면서 그 규칙을 지키는 것이 첫 시험이다.**

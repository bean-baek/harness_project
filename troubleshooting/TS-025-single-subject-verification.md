---
id: TS-025
title: 모든 검증이 피험체 한 명을 봤다 — 두 번째 프로젝트에 닿자 5개 결함이 동시에 드러났다
date: 2026-10-03
category: verification-design
severity: high
status: resolved
component: harness/project.py, harness/independence.py, harness/inspect.py, harness/runner.py
tags: [verification-design, single-subject, portability, convention, recurrence]
guard: `verification/fixtures/` 의 외부 모양 픽스처를 CI 가 매 푸시마다 검사한다
exposure: runner-verified
resolution: use
---

## Symptoms

TS-017 에서 하네스를 "모든 프로젝트에 붙일 수 있게" 외부화했다. 그 작업은
회귀 검증 91건을 통과했고, 누적 699건이 녹색이었다.

그런데 **실제 두 번째 프로젝트에 붙이자마자** 결함이 나왔다. 하나가 아니라 다섯이다.
다섯 모두 `web_target`(React + TypeScript + jest) 에서는 **구조적으로 드러날 수 없는**
것이었다.

| | 증상 | 생존 기간 |
|---|---|---|
| 1 | `--project` 로 외부 프로젝트를 지정해도 **이 레포의 설정**(jest)이 적용됐다 | 5커밋 |
| 2 | `test_app.py` 가 테스트 파일로 **인식되지 않았다** (pytest 관례) | 처음부터 |
| 3 | `independence` 가 파이썬 컬렉션을 **하나도** 찾지 못했다 | TS-020 부터 |
| 4 | `from mod import X` 로 앱의 선언을 읽는 pytest 테스트가 **'자급'으로 오탐** | TS-020 부터 |
| 5 | 커버리지 집계가 **테스트 파일 자신을 증거로 계수**했다 (pytest) | 처음부터 |

2·3·4·5 는 전부 같은 모양이다 — **JS 의 문법과 관례가 코드에 박혀 있고, 설정은
`.py` 를 지원한다고 선언한다.** 선언과 구현이 어긋났고 아무도 묻지 않았다.

## Root cause

### 직접 원인 — 규약 판정이 네 곳에 따로 구현돼 있었다

`ProjectConfig.all_test_suffixes()` 는 "테스트 파일 규약"을 돌려준다. 호출자가 넷이고
**네 곳 모두 `str.endswith` 로 직접 비교했다.**

```
harness/tags.py:_kind_of                    name.endswith(suffixes)
harness/independence.py:declared_collections p.name.endswith(test_suffixes)
harness/inspect.py:_source_files             p.name.endswith(suffixes)
harness/inspect.py:_test_files               p.name.endswith(suffixes)
harness/runner.py:_is_source                 name.endswith(all_test_suffixes())
```

접미사 비교는 JS 에서 맞다 — `.test.tsx` 는 실제로 접미사다. 그러나 **pytest 의 관례는
접두사다**(`test_app.py`). 접미사로 표현할 방법이 없다. 기본값에는 그 불가능을
`"test_.py"` 라는 **의미 없는 문자열**로 적어 두었고, `endswith("test_.py")` 는
어떤 파일에도 맞지 않는다.

결과가 호출자마다 반대 방향으로 틀렸다:

```
_kind_of              테스트를 못 찾는다   → 게이트가 모든 기능을 거부
_test_files           테스트를 못 찾는다   → 검수가 "테스트 0개" 라고 보고
_source_files         테스트를 소스로 센다 → 미테스트 소스 수가 부풀려진다
declared_collections  테스트를 소스로 센다 → 테스트의 배열을 '앱의 선언'으로 오인
_is_source            테스트를 증거로 센다 → 커버리지가 과대평가된다
```

마지막 것이 가장 나쁘다. **커버리지 게이트는 "선언한 기능이 실제로 실행되는가"를
묻는 장치인데, 테스트 자신의 줄을 세면 아무것도 실행하지 않는 테스트도 높은
커버리지를 받는다.** 그것은 TS-016 에서 막은 바로 그 결함이다 — pytest 경로에서만
되살아나 있었다.

### 더 나쁜 사실 — `_detect_suffixes` 가 깨진 값을 **생산**했다

검수 명령은 프로젝트를 훑어 규약을 실측한다. pytest 분기는 `test_` 접두사 파일을
**정확히 세고** 있었다. 그리고 그 결과를 `"test_.py"` 로 적었다. 즉 사실을 알고 있었고
표현할 어휘가 없었다. 자동 검수가 틀린 설정을 만들어 주는 쪽이 아무 설정도 없는
쪽보다 나쁘다 — 사람이 그것을 보고 "검수가 했으니 맞겠지" 라고 생각한다.

### 구조 원인 — 검증이 피험체 한 명만 봤다

왜 699건이 전부 놓쳤는가. **모든 회귀 검증이 `web_target` 을 봤다.**

`web_target` 은 React + TypeScript + jest 다. 그 모양에서는
- 설정이 하네스 루트에 있으므로 `config_for` 의 하드코딩이 **정답과 같은 값**을 낸다
- 테스트 규약이 실제로 접미사이므로 `endswith` 가 **맞다**
- 컬렉션 선언에 `const` 가 있으므로 정규식이 **맞다**
- named import 에 중괄호가 있으므로 `_imports` 가 **맞다**

다섯 결함 전부가 `web_target` 에서는 **증상이 없다.** 검증을 아무리 촘촘하게 더해도
잡히지 않는다. 테스트를 더 쓰는 것으로는 해결되지 않는 종류의 구멍이다 —
**다른 모양이 존재한다는 사실 자체가 테스트 집합에 없었다.**

README 는 pytest 경로를 "단위 검증으로 확인했다"고 적었다. 사실이다. 그 단위 검증이
`_test.py` 형태만 썼다 — 접미사로 표현 **가능한** 쪽만. 검증을 쓴 사람(나)이 접두사
관례를 몰랐으므로, 그 사람이 쓴 검증은 그 무지를 그대로 물려받았다.

이것은 [TS-024](TS-024-published-numbers-go-stale.md) 에서 정리한 원인 1
("도구와 그 도구의 테스트를 같은 사람이 같은 이해로 만든다")의 가장 선명한 사례다.
TS-024 가 원인 2 로 적은 것이 바로 이것이고, 여기서 실제로 터졌다.

## Fix

### 1. 규약 판정을 한 곳으로 — `project.matches_pattern` + `cfg.is_test_file`

```python
def matches_pattern(name: str, patterns: tuple[str, ...]) -> bool:
    """`*`·`?` 가 있으면 글로브(`test_*.py`), 없으면 접미사(`.test.ts`)."""
    for pat in patterns:
        if "*" in pat or "?" in pat:
            if fnmatch(name, pat):
                return True
        elif name.endswith(pat):
            return True
    return False
```

`ProjectConfig.is_test_file` 이 이것을 감싸고, **네 호출자가 전부 그것만 쓴다.**
`project.py` 에 두는 이유: 규약은 설정의 책임이고 `project.py` 는 하네스 안에서
아무것도 import 하지 않는 잎이다. `tags` 는 재노출한다.

호출자 중 하나(`runner._is_source`)는 파일명이 아니라 커버리지가 뱉은 **경로**를
넘긴다 — `tests/test_convert.py`. 접미사 비교는 경로에서도 맞지만 글로브는 맞지
않는다(`fnmatch("tests/test_convert.py", "test_*.py")` 는 거짓). 정규화를
`is_test_file` 안에서 하여 호출자가 기억할 규칙을 하나 줄였다.

### 2. 기본값과 검수 출력을 글로브로

```python
"pytest": {
    "unit_suffixes": ["test_*.py", "*_test.py"],
    "e2e_suffixes":  ["*_e2e.py", "e2e_*.py"],
}
```

`_detect_suffixes` 도 같은 어휘로 출력한다. 접미사 동작은 그대로이므로 기존
`.harness.json` 은 손댈 필요가 없다.

### 3. 컬렉션 정규식에 파이썬 갈래 — 선언 키워드가 없는 쪽

```python
_COLLECTION_RE = re.compile(
    r"(?:(?:export\s+)?(?:const|let|var)\s+|^[ \t]*)"
    r"([A-Z][A-Z0-9_]*)\s*(?::[^=\n]+?)?=\s*\[([^\]]*)\]",
    re.MULTILINE,
)
```

키워드 없는 쪽은 **줄 머리만** 받는다. `obj.FOO = [...]` 같은 대입을 선언으로
오인하지 않기 위해서다.

### 4. `_imports` 에 파이썬 named import

JS 는 중괄호를 쓰지만 파이썬은 쓰지 않는다. 괄호로 감싼 여러 줄 import 까지 본다.

```python
for m in re.finditer(r"from\s+[\w.]+\s+import\s+(\([^)]*\)|[^\n]*)", text):
    if re.search(rf"\b{re.escape(name)}\b", m.group(1)):
        return True
```

### 5. 구조 수정 — 외부 프로젝트 픽스처를 CI 에 (핵심)

위 네 개는 증상 치료다. **원인은 피험체가 하나였다는 것**이므로 처방도 거기에 둔다.

`verification/fixtures/` 에 `web_target` 과 **모든 칸이 다른** 프로젝트 둘을 넣고
`repro_ts025.py` 가 매 CI 마다 검사한다.

| | web_target | vanilla-js | pytest-app |
|---|---|---|---|
| 런너 | jest | vitest | pytest |
| 단위 규약 | `.test.tsx` | `.test.js` | `test_*.py` (접두사) |
| ID 형식 | `F-\d{3}` | `APP-\d{2}` | `PY-\d{2}` |
| 타입 검사 | tsc | 없음 | 없음 |
| 설정 위치 | 하네스 루트 | 프로젝트 자신 | 프로젝트 자신 |
| 언어 | TypeScript | JavaScript | Python |

**이 픽스처가 다섯 결함 중 다섯 개를 다 잡았다.** 세 개는 픽스처를 만드는 중에
나왔고(2·3·4), 하나는 검증 스크립트를 돌리자 나왔고(5), 하나는 그 전에 실 프로젝트에서
나왔다(1). 699건이 하나도 못 잡은 것을 픽스처 12개 파일이 전부 잡았다.

## Verification

```
python verification/repro_ts025.py      # 58건
```

검사 항목 — 각 픽스처에 대해:
설정 해소 순서(프로젝트 자신 > 하네스 기본), 런너 식별, 규약 판정(접두사·접미사·글로브),
태그 스캔, 비표준 ID 형식, 명세 로드 위치, 런너 3단 가용성 판정,
컬렉션 선언 수집, 파이썬 import 인식, `is_test_file` 의 네 호출자 전부,
검수 보고, 그리고 픽스처가 하네스 자기 감사를 오염시키지 않는가.

## 범위 — 이 픽스처가 **하지 않는** 것

정적 계층만 본다. **런너를 설치하지 않는다.**

| 계층 | jest | vitest | pytest |
|---|---|---|---|
| 정적 (설정·태그·명세·검수) | CI | **CI (신규)** | **CI (신규)** |
| 런너 실행 (테스트·커버리지) | CI | 실 프로젝트 수동 실측 | **한 번도 안 했다** |

`npm ci` / `pip install pytest pytest-cov` 를 CI 에 넣으면 메워진다. 넣지 않은 이유는
비용이 아니라 순서다 — 다섯 결함 중 넷이 정적 계층이었고, 정적 계층은 설치 0으로
매 푸시마다 돌 수 있다. 메우지 않았다는 사실을 `repro_ts025.py` 의 [9] 블록이
**출력에 적어** 조용한 공백이 되지 않게 했다.

pytest 실행 경로는 따라서 **여전히 미검증**이다. 이 문서가 그 사실의 기록이다.

## Lesson

**"일반화했다"는 주장은 두 번째 사례로만 검증된다.**

TS-017 은 하드코딩을 전부 설정으로 뺐고, 그 작업 자체는 옳았다. 설정으로 뺀 것과
**다른 값이 실제로 동작하는 것**은 다른 명제다. 전자는 코드를 읽으면 확인되고
후자는 **다른 값을 넣어 돌려봐야** 확인된다. 699건은 전부 전자만 확인했다.

같은 형태의 질문을 앞으로 남은 추상화마다 해야 한다 —
`SOURCE_EXTS` 에 `.go` 를 넣으면? ID 형식에 한글을 쓰면? 모노레포라면?
각 질문의 답은 "코드를 보니 될 것 같다"가 아니라 **픽스처 한 개**다.

---
id: TS-031
title: 새 언어 체크리스트를 실제로 따라가니 결함 7건이 나왔다 — 그중 하나는 거짓 통과였다
date: 2026-10-04
category: verification-design
severity: high
status: resolved
component: harness/runner.py, harness/tags.py, harness/inspect.py, harness/status.py
tags: [runner, unittest, false-pass, checklist, execution-layer, self-verification]
guard: `unittest` 런너의 실행 계층을 CI 가 매 푸시마다 끝까지 돌린다 (`런너 실행 계층: unittest` 단계). 체크리스트에서 실측한 함정 넷이 문서와 `repro_ts031.py` 에 음성 대조로 고정돼 있다
exposure: language-matrix
resolution: accept
---

## Symptoms

[TS-030](TS-030-no-stop-rule-and-hidden-layer-gaps.md) 에서 `docs/adding-a-language.md`
를 쓰고 이렇게 주장했다.

> 필수 (이것만 하면 게이트가 돈다)
>   1. `Runner` 서브클래스 — 메서드 4개
>   2. 픽스처 1개

**그 주장은 검증되지 않은 것이었다.** 그리고 TS-025 는 정확히 그런 주장이 두 번째
사례에서 깨진 기록이다 — "모든 프로젝트에 붙는다"고 선언한 뒤 결함 5개가 나왔다.

그래서 절차를 **실제로 따라가** `unittest` 런너를 붙였다. 결함 7건이 나왔다.

가장 나쁜 것은 **거짓 통과**였다. 게이트가 `UT-01` 을 통과시켰는데, 실제로는
**테스트가 하나도 실행되지 않았다.** 커버리지 4줄은 모듈 import 만으로 생긴 것이었다.

```
UT-01: 커버리지   4  줄=[11, 13, 16, 25]      ← 모듈 수준 선언만
패턴 없이 돌리면  9  줄=[11,13,16,18..22,25]  ← convert() 본문이 포함됨
```

[TS-016](TS-016-vacuous-evidence-passes-the-gate.md) 이 막은 "아무것도 실행하지 않는
증거가 완벽한 증거로 계수된다"가 **새 런너에서 되살아났다.**

## 왜 `unittest` 를 골랐는가

이 선택 자체가 측정이었다.

```
go / cargo      설치 안 됨 → 정적 계층밖에 못 본다
pytest          설치 안 됨 (requirements.txt 에도 없다)
unittest        **stdlib** → 설치 0
coverage        7.16.2 설치됨 → 줄 지도까지 얻을 수 있다
```

`unittest` 는 **설치 0으로 런너 실행 계층을 CI 에서 돌릴 수 있는 유일한 파이썬 경로**다.
TS-025·TS-030 이 "jest 만 실행 계층이 CI 에 있다"를 공백으로 기록했고, 이것이 그
공백을 메운다. 그래서 가장 가치 있는 선택이었다.

그리고 `coverage json` 의 모양이 `pytest-cov` 와 **완전히 같았다**(실측) —
`files: {path: {executed_lines, missing_lines, summary}}`. 그래서 `_parse_coverage` 를
그대로 재사용했다. 새 코드가 아니라 **기존 코드의 재사용**이 가능한지도 측정으로 확인했다.

## 결함 7건

### ① `name_pattern` 이 정규식인데 문자열 포함으로 비교했다 — **거짓 통과**

```python
feature_name_pattern("UT-01")  →  'UT\\-01(?![0-9])'
```

jest 의 `--testNamePattern` 방언이다. 내 수집기는 `pattern in label` 로 비교했고,
그 정규식 문자열은 어떤 라벨에도 **포함되지 않는다.** 결과:

```
선택된 테스트 0개 → 빈 스위트 → 모듈 import 만 실행 → 커버리지 4줄 > 0 → 게이트 통과
```

커버리지 게이트는 "비(非)테스트 소스 1줄 이상"을 요구한다. 모듈 수준 선언이 그
조건을 만족시킨다. **임계값이 아니라 조건이 느슨한 것이 아니고, 범위 제한이 깨진 것이
원인**이다.

### ② `unittest` 의 `testNamePatterns` 를 쓰면 안 된다

처음에는 라이브러리 기능을 쓰려고 `loader.testNamePatterns` 를 썼다. 그것은
**메서드 이름**에 매칭된다. 파이썬 식별자에 하이픈을 쓸 수 없어
`def test_UT-01_...` 이 불가능하므로 기능 ID 는 **docstring** 에 있다.
하네스가 보는 이름(`shortDescription()`)과 그 필터가 보는 이름이 **다르다.**

필터는 하네스의 이름 정의 기준이어야 한다 — 그 정의가 수집기 안에 있으므로 거기서 거른다.

### ③ 수집기를 임시 파일로 실행하면 `sys.path` 가 달라진다

`python <script>` 는 **스크립트의 디렉터리**를 `sys.path[0]` 에 넣는다. 수집기는
임시 디렉터리에 쓰이므로 대상 프로젝트가 경로에 없다.

```
loadTestsFromNames(["tests.test_wallet"])
  → import 실패 → unittest.loader._FailedTest
  → 그 가짜 테스트의 이름에 기능 ID 가 없다 → 필터가 전부 걸러낸다
  → 다시 ①과 같은 결과
```

`discover` 는 `top_level_dir` 을 `sys.path` 에 넣어 주므로 **그 경로만 우연히
동작했다.** 수집기 안에서 `sys.path.insert(0, os.getcwd())` 를 해야 한다.

### ④ 패턴이 0개를 맞추면 '통과'가 아니라 '측정 실패'다

빈 스위트는 `wasSuccessful()` 이 **True** 다. `run_scoped` 가 0 을 돌려주면
돌연변이가 "변이를 잡지 못했다"(생존)로 센다. 종료 코드 3 으로 구분해
`run_scoped` 가 `None`(측정 실패)을 돌려준다 — 과소평가는 안전한 방향이다
(점수를 좋게 보이게 만들지 않는다).

### ⑤ `_imported_stems` 가 JS 전용이었다 — 기존 검사기의 오탐

```
JS       from './x'            ← 따옴표가 있다
파이썬    from src.wallet import X  ← 없다
```

JS 정규식만 쓰던 `check_untested_sources` 는 파이썬 테스트가 소스를 import 해도 못 보고
**"소스 2개 중 2개에 도달하지 않습니다"** 를 보고했다. TS-025 의 `_imports` 결함과
같은 가족이고, 같은 곳을 또 놓쳤다.

### ⑥ `__init__.py` 를 stem 으로 찾아 패키지 import 를 놓쳤다

`from src.wallet import X` 는 `src` 패키지를 import 하므로 `src/__init__.py` 가
실행된다. 그런데 그 파일의 stem 은 `__init__` 이라 `src` 와 매칭되지 않았다.
`__init__.py` 는 **디렉터리 이름**으로 불러야 한다.

### ⑦ 지원 표가 하드코딩 딕셔너리를 썼다 — **자기 자신을 어겼다**

TS-030 의 지원 표는 "손으로 적으면 조용히 거짓이 된다"를 막으려고 만든 생성 파일이다.
그런데 그 안에 이런 것이 있었다.

```python
exts = {"jest": ".tsx", "vitest": ".jsx", "pytest": ".py"}.get(name, "")
```

`unittest` 가 거기 없으니 **검수·컬렉션·초안이 전부 `—`** 로 나왔다 — 실제로는 검수와
컬렉션이 동작하는데도. 손으로 적은 표를 막으려고 만든 표 안에서 같은 실수를 했다.

수정: 피험체의 **실제 소스 파일**에서 확장자를 읽고, 변이 매칭도 **모든 소스 파일에
걸쳐** 센다. 처음에는 첫 파일 하나만 봤는데 그러면 어느 파일이 먼저 정렬되는지에
수치가 달라진다 — 손으로 적은 대표 구문만큼이나 임의적이다.

### 덤 — `is_suite` 가 파이썬에서 항상 거짓이었다

`is_suite = bool(suite_re.search(line))` 는 **같은 줄**에서 찾는다.

```
JS       describe('F-005: …')          ← 같은 줄
파이썬    class ConvertTest(TestCase):  ← 선언
             """UT-01: …"""            ← 라벨 (다음 줄)
```

**pytest 픽스처도 0건이었다** — TS-025 때부터 있었고 아무도 `is_suite` 를 보지
않았다. 게이트 판정에 쓰이지 않으므로 기능 영향은 없지만, 필드가 뜻을 주장하면서
조용히 거짓이었다. 파이썬 계열은 선언 **직후 한 줄**까지 스위트로 본다.

### 그리고 문서 자신이 틀렸다

```bash
python -m harness.cli inspect --project ./your-app    # ← 그런 플래그가 없다
```

`inspect` 는 `--harness-root` 를 받는다. 체크리스트를 따라간 첫 명령이 바로 실패했다.

## Fix

`UnittestRunner` 를 `harness/runner.py` 에 추가했다. `PytestRunner` 를 상속하는
이유는 하나다 — 커버리지 JSON 파싱이 **완전히 같다.** 그 외는 전부 재정의한다.

핵심은 `_UNITTEST_COLLECTOR` 다. **사람이 읽는 출력을 파싱하지 않는다** —
`unittest -v` 는 docstring 이 있으면 두 줄로 쪼개고 상태를 둘째 줄에 붙인다.

```
test_ut01_1_x (tests.test_conv.ConvertTest)
UT-01.1: 선언된 통화는 전부 변환된다 ... ok     ← docstring 있음: 두 줄
test_ut02_1_y (tests.test_conv.Demo) ... skipped   ← 없음: 한 줄
```

파싱 규칙이 docstring 유무에 따라 달라진다 — [TS-021](TS-021-mutation-operators-tested-the-compiler.md)
의 함정(출력 형식을 시험하는 코드)과 같다. stdlib 에 JSON 리포터가 없을 때의 올바른
답은 **그 생태계의 API 를 쓰는 것**이다. `unittest.TextTestResult` 를 상속한 수집기를
임시 파일로 써서 실행하면 형식에 의존하지 않는다 — jest 의 `--json` 과 같은 수준이다.

### 실행 계층이 CI 에 들어갔다

```yaml
- name: 커버리지 도구 (unittest 픽스처용)
  run: pip install coverage

- name: "런너 실행 계층: unittest — 증거 게이트를 끝까지 돌린다"
  run: |
    python -m harness.cli verify UT-01 --project verification/fixtures/unittest-app
    python -m harness.cli verify UT-02 --project verification/fixtures/unittest-app
```

단계 이름의 `런너 실행 계층: unittest` 가 **지원 표의 선언**이다. `cli status` 가 그
문자열을 읽어 'CI 실행 O' 로 적는다 — 호출 형태를 추측하지 않는다(하네스를 통해
돌리면 커맨드에 런너 이름이 안 나온다). TS 문서의 `exposure:` 와 같은 방식이고,
선언이 없으면 `—` 로 **과소** 보고한다.

그 단계 이름을 **따옴표로 싸야 한다.** `: ` 가 들어가면 YAML 이 매핑으로 읽는다 —
따옴표 없이 쓰고 `yaml.safe_load` 로 확인했더니 `ScannerError` 였다. CI 가 돌기
전에 잡았다.

### 결과 — 지원 표

```
| 런너 | 피험체 | 게이트 | CI 실행 | 검수 | 컬렉션 | 초안 | 줄 변이 |
| jest     | web_target    | O | O | O | O | O | 59곳 |
| pytest   | pytest-app    | O | — | O | O | — |  0곳 |
| unittest | unittest-app  | O | O | O | O | — |  0곳 |
| vitest   | vanilla-js    | O | — | O | O | O |  4곳 |
```

`unittest` 가 **jest 외에 유일하게 CI 실행 O** 다. 줄 변이 0곳은 정직한 값이고,
컬렉션 멤버 제거 변이는 파이썬에서도 동작한다 — 실측에서 `CURRENCIES` 의 멤버 3개가
제거됐고 전부 `out-of-spec` 으로 분류됐다. 픽스처 명세가 통화를 **지목하지 않기**
때문이고, 그것이 [TS-023](TS-023-survivor-means-two-things.md) 의 구분이 파이썬에서도
작동한다는 증거다.

## Verification

```
python verification/repro_ts031.py
```

**다른 검증 스크립트와 달리 실제로 런너를 돌린다** (설치 0). `coverage` 가 없으면
커버리지 검사만 건너뛰고 **그 사실을 출력한다** — 건너뛴 것을 통과로 적지 않는다.

음성 대조 넷:

```
PASS  음성 대조: 문자열 포함으로는 매칭되지 않는다
PASS  음성 대조: sys.path 없이는 import 가 실패한다
PASS  패턴이 0개를 맞추면 None (측정 실패)
PASS  음성 대조: 따옴표 정규식만으로는 파이썬을 못 본다
PASS  검수 계층 O (하드코딩 매핑을 쓰지 않는다)
```

그리고 **문서가 실측한 함정을 담았는지**를 검사한다. 문서와 코드가 어긋나면 실패한다.

## Lesson

**절차를 쓴 사람이 그 절차를 따라가 보지 않으면, 그것은 검증되지 않은 주장이다.**

TS-030 에서 체크리스트를 썼고 "필수 둘만 하면 게이트가 돈다"고 적었다. 실제로 따라가니
**필수 둘을 지켜도 게이트가 거짓 통과를 냈다.** 빠진 것은 문서에 없던 함정 넷이었고,
넷 다 "범위 제한이 조용히 깨진다"는 한 가족이다.

이것은 TS-025 의 반복이다 — 그때는 "모든 프로젝트에 붙는다"는 주장이 깨졌고, 이번에는
"이 절차를 따르면 붙는다"는 주장이 깨졌다. **일반화를 주장하는 문서도 두 번째 사례로만
검증된다.** 코드와 다르지 않다.

그리고 ⑦이 가장 뼈아프다. 손으로 적은 표가 조용히 거짓이 되는 것을 막으려고 생성 표를
만들었고, **그 생성 코드 안에 손으로 적은 표를 넣었다.** 처방을 쓰면서 처방의 대상이
되는 실수를 같이 했다. TS-030 의 무한 재귀와 같은 모양이다 — **규칙을 만들 때 그 규칙을
자기 코드에 먼저 적용해야 한다.**

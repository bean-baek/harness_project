# 새 언어·런너를 붙이는 절차

하네스의 계층은 **생태계에 묶인 정도가 서로 다르다.** 전부 넓힐 필요는 없다 —
당신 작업을 지키는 게이트는 **런너 클래스 하나**로 돈다.

현재 지원 현황은 손으로 적지 않는다. [docs/status.md](status.md) 의 "언어·런너 지원"
표가 `RUNNERS`·픽스처·CI·연산자 표를 **읽어서** 생성한 것이고, `cli status --check` 가
드리프트를 막는다 (TS-024).

---

## 계층과 비용

| 계층 | 무엇을 하는가 | 새 언어에 필요한 것 | 비용 |
|---|---|---|---|
| **게이트** | 통과 플래그를 증거로 강제 | `Runner` 서브클래스 1개 | **작다** |
| 태그 스캔 | 테스트가 어느 기능을 검증하는지 | `_suite_regex` 분기 1개 | 작다 |
| 검수 | 선언과 구현의 불일치 | `SOURCE_EXTS` 에 확장자 추가 | 작다 |
| 컬렉션 | 단일 출처 선언을 찾는다 | `_COLLECTION_RE` 에 갈래 1개 | 중간 |
| 명세 초안 | 선언에서 문장을 뽑는다 | 그 언어의 **선언 문법** | 중간 |
| **돌연변이** | 증거가 실제로 무는가 | 그 언어의 **연산자 표** | **크다** |

**게이트만 되면 하네스의 핵심은 전부 동작한다.** 돌연변이는 기본값이 꺼짐
(`HARNESS_REQUIRE_MUTATION_EVIDENCE=false`)이고, 나머지는 보고 전용이다.

---

## 필수 — 이 둘만 하면 게이트가 돈다

### 1. `Runner` 서브클래스

`harness/runner.py` 에 넣는다. 메서드 네 개다.

```python
class GoRunner(Runner):
    name = "go"

    def launcher(self) -> list[str] | None:
        """실행 커맨드 접두사. None 이면 '실행 불가'를 뜻한다.

        **없는데 있다고 하지 말 것** — `available()` 이 '실행 가능'으로 보고하면
        게이트가 돌지 않는데도 통과처럼 보인다 (TS-017 에서 실측된 오탐).
        """
        return ["go", "test"] if shutil.which("go") else None

    def run_all(self, path=".", coverage=False) -> tuple[int | None, str]:
        """전체 스위트. 사람이 읽을 출력."""

    def results(self) -> tuple[Results | None, str]:
        """구조화된 결과 — **개별 테스트 이름과 상태**가 필요하다.
        게이트가 기능 ID 를 인용하는 테스트를 찾기 때문이다 (TS-008).
        `go test -json` 이 그것을 준다."""

    def coverage(self, test_files, name_pattern) -> tuple[Coverage | None, str]:
        """주어진 테스트만 돌려 **소스별 실행 statement 수 + 실행된 줄 번호**.

        줄 번호가 없으면 돌연변이가 미실행 줄에 변이를 넣는다 (TS-026).
        `go test -coverprofile` 이 줄 단위로 준다 — `per_file` 과
        `executed_lines` 를 모두 채울 것.
        """
```

**지켜야 하는 계약 두 개:**

- 모든 연산은 `(값, 진단)` 을 돌려주고 값이 `None` 이면 **측정 실패**다.
  측정 실패는 '통과'가 아니다 (TS-016). 게이트가 `None` 을 거부로 처리한다.
- 테스트를 **멈추게 하지 말 것.** `vitest` 를 인자 없이 부르면 watch 모드로
  영원히 멈춘다. 그래서 `pre_args = ("run",)` 가 있다. 당신 런너에 비슷한
  함정이 있는지 확인할 것.

### 2. 픽스처 — **협상 불가**

`verification/fixtures/<이름>/` 에 작은 프로젝트를 만든다.

```
verification/fixtures/go-app/
  .harness.json        runner, id_pattern, unit_suffixes, source_dirs
  features.json        기능 2개 정도
  src/...              소스
  ..._test.go          태그된 테스트
```

**왜 협상 불가인가**: TS-025 가 그 증거다. 픽스처 없이 "일반화했다"고 주장했고,
두 번째 프로젝트에 닿는 순간 결함 5개가 나왔다. 넷은 `web_target` 의 모양에서는
**증상이 없는** 것이었다 — 회귀 검증 699건이 하나도 잡지 못했다.

픽스처의 모든 칸이 기존 피험체와 **달라야** 한다. 같으면 아무것도 검증하지 않는다.

| | web_target | 당신 픽스처 |
|---|---|---|
| 런너 | jest | 새 런너 |
| 단위 규약 | `.test.tsx` | 그 생태계의 관례 |
| ID 형식 | `F-\d{3}` | 다른 형식 |
| 설정 위치 | 하네스 루트 | **프로젝트 자신** |

그리고 `repro_ts025.py` 에 그 픽스처에 대한 정적 검사를 추가한다 — 설정 해소,
런너 식별, 규약 판정, 태그 스캔, 명세 로드.

---

## 선택 — 원하면 넓힌다

### 3. 태그 스캔 정규식

테스트 이름 규약이 다를 때만. `harness/tags.py` 의 `_suite_regex` 에 분기를 넣는다.

pytest 가 왜 다른지가 좋은 예다 — 함수 이름(`def test_f005_...`)에 하이픈을 쓸 수
없어 `F-005` 가 들어가지 않는다. 그래서 **docstring 문자열**을 본다.

### 4. 컬렉션 선언 정규식

`harness/independence.py` 의 `_COLLECTION_RE`. 이미 두 갈래가 있다 —
JS 는 `const X = [...]`, 파이썬은 **선언 키워드가 없다**(`X = [...]`).
키워드 없는 쪽은 **줄 머리만** 받는다. `obj.FOO = [...]` 같은 대입을 선언으로
오인하지 않기 위해서다.

### 5. 돌연변이 연산자 — 가장 비싸고 가장 안 정확하다

먼저 **측정하라.** 지금 연산자가 그 언어에 몇 곳 매칭되는지 세 본다.

```python
from harness.mutate import MUTATIONS, _candidate_lines
src = open("your_file.go").read()
for name, pat, _ in MUTATIONS:
    print(name, len(_candidate_lines(src, pat)))
```

파이썬에서 재면 **전부 0** 이다 — `===`·`&&` 가 없고 `if` 에 괄호를 쓰지 않는다.
즉 돌연변이 측정이 그 언어에서 아무것도 하지 않는다. `docs/status.md` 의 표가
이 수치를 싣는다.

연산자를 추가할 때 **TS-021 의 함정**을 반드시 피할 것:

> `>` → `>=` 규칙이 **190곳**에 매칭됐고 진짜 비교는 **3곳**뿐이었다. 나머지는
> JSX 태그(108곳)와 제네릭(32곳)이라 치환하면 `React.FC<Props>` 가
> `React.FC<Props>=` 가 되는 **구문 파괴**였다. 변이가 테스트를 시험하는 게
> 아니라 컴파일러를 시험했고, '폐기' 집계가 그 사실을 가렸다.

그래서:

- 연산자를 추가하면 **매칭 수를 세고, 그중 진짜가 몇 개인지 눈으로 확인**한다
- 정규식으로 **괄호를 맞출 수 없다.** 중첩 괄호가 필요하면 전용 함수를 쓴다
  (`neutralize_condition`·`_attr_value` 가 그 예다)
- 변이 뒤 **정적 검사**로 유효성을 확인한다. 정적 검사 커맨드가 없는 프로젝트는
  구문 파괴를 '테스트가 잡았다'로 세어 **점수가 과대평가된다** —
  `cli exposure` 가 그것을 TS-021 노출로 보고한다

---

## 붙인 뒤 확인

```bash
python -m harness.cli inspect --project ./your-app    # 붙을 수 있는가
python -m harness.cli exposure --project ./your-app   # 어떤 실패 모드에 노출됐는가
python -m harness.cli status                          # 지원 표 재생성
python verification/repro_ts025.py                    # 픽스처 정적 검사
python -m harness.cli exposure                        # 선언/검사기 일치 (종료 코드 1 이면 어긋남)
```

`cli exposure` 가 **"이 런너는 검증된 적 없다"** 고 말해주는 것이 핵심이다.
정적 계층만 픽스처가 있고 런너 실행 계층은 CI 에 없으면 그렇게 적힌다 — 그 공백을
숨기지 않는 것이 TS-025 의 처방이다.

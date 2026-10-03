"""
TS-028 검증 스크립트 — 명세 초안이 명세가 아니었다
──────────────────────────────────────────────
`inspect --write-draft` 는 '명세 초안'을 만든다고 선언했지만 실제로는 **검수 발견
사항을 기능처럼 포장**했다. 실측한 초안 4건 전부:

  F-001  "모든 소스 파일이 최소 한 개의 테스트에서 import 된다"   ← 코드 위생 규칙
  F-002  "export 된 모든 심볼이 어딘가에서 참조된다"               ← 코드 위생 규칙
  F-003  "LoginForm 의 입력 검증 규칙"                            ← 주제, 내용 없음
  F-004  "UserMenu 의 실패 시 동작"                               ← 주제, 내용 없음

앞의 둘은 **앱의 기능이 아니다** — 사용자가 관찰할 행동이 없고 `steps` 를 채울 수도
없다. 뒤의 둘은 "명세가 필요한 자리"를 가리키지만 **내용이 없다.** 그리고 ID 가
`F-001` 부터 시작해 **기존 명세와 충돌**했다.

수정의 핵심 판단 — 무엇이 순환이고 무엇이 아닌가:

  순환:   구현의 **제어 흐름**을 읽어 명세로 올린다. 그 구현으로 그 구현을 검사한다.
  불변식: **선언**을 읽고 **런타임 행동**을 검사한다. 두 지점이 다르다.

그래서 **상태 조건부 선언만** 쓴다 (`disabled={loading}`). 무조건 속성
(`role="main"`)은 쓰지 않는다 — 뽑아낸 그 속성을 그대로 다시 읽는 한 지점 검사다.

이 스크립트가 고정하는 음성 대조 (설계 규약 1):
  · 코드 위생 규칙이 초안에 **들어오지 않는다**
  · 무조건 속성에서 초안을 만들지 **않는다**
  · 생성된 ID 가 기존 명세와 겹치지 **않는다**
  · 생성된 ID 가 선언된 `id_pattern` 에 **맞는다** (APP-003 은 형식 위반이었다)

LLM·네트워크를 쓰지 않는다.
"""
import re
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import draft
from harness import inspect as inspect_mod
from harness import project as project_mod
from harness.verify import config_for, load_features

ok = 0
fail = 0
NL = chr(10)


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


print("\n[1] 속성 값 추출 — 중괄호를 센다 (정규식으로는 안 된다)")
# 실측한 결함: `[^}]` 는 템플릿 리터럴의 `${...}` 첫 `}` 에서 멈춰
# `emailError ? \`${emailId` 라는 쓰레기 조건식을 냈다.
nested = 'aria-describedby={err ? `${id}-error` : undefined} other'
at = nested.index("{")
got = draft._attr_value(nested, at)
check("중첩 중괄호를 넘어 끝까지 읽는다", got[0], "err ? `${id}-error` : undefined")
check("음성 대조: 정규식 [^}] 는 첫 } 에서 끊긴다",
      re.search(r"\{([^}]*)\}", nested).group(1), "err ? `${id")
check("값이 리터럴이면 None (상태 조건부가 아니다)",
      draft._attr_value('type="email"', 5), None)
check("닫히지 않은 중괄호는 None", draft._attr_value("{unclosed", 0), None)
check("중괄호 안의 문자열에 든 } 를 세지 않는다",
      draft._attr_value('{x === "}" }', 0)[0], 'x === "}" ')
# 보간 깊이를 중괄호 깊이와 **따로** 세지 않으면 백틱 안의 리터럴 `}` 가
# JSX 중괄호를 닫은 것으로 계수되어 값을 끝까지 못 읽는다.
check("백틱 안의 리터럴 } 를 닫는 괄호로 보지 않는다",
      draft._attr_value("{`a}b`}", 0)[0], "`a}b`")
check("보간이 여러 개여도 끝까지 읽는다",
      draft._attr_value("{`${a}-${b}`}", 0)[0], "`${a}-${b}`")
check("보간 안의 중괄호도 처리한다",
      draft._attr_value("{`${f({k: 1})}`}", 0)[0], "`${f({k: 1})}`")

print("\n[2] 조건식 — 삼항에서 조건만 남기는가")
check("삼항의 조건만", draft._condition_of("err ? `${id}-error` : undefined"), "err")
check("이중 부정을 줄인다", draft._condition_of("!!emailError"), "emailError")
check("단일 부정은 유지한다 (의미가 다르다)", draft._condition_of("!isValid"), "!isValid")
check("논리식은 그대로", draft._condition_of("!isValid || loading"), "!isValid || loading")
check("문자열 안의 ? 를 삼항으로 보지 않는다",
      draft._condition_of('q === "a?b"'), 'q === "a?b"')
check("공백을 정리한다", draft._condition_of("  a   &&\n  b  "), "a && b")

print("\n[3] 조사 — 받침에 맞게 고르는가")
# "제출 버튼**가** 비활성화된다" 가 실제 출력이었다. 초안은 사람이 읽고 판단할
# 문장이므로 읽히지 않으면 목적을 잃는다.
j = draft._josa
check("받침 있음 → 이", j("버튼#이가"), "버튼이")
check("받침 없음 → 가", j("체크박스#이가"), "체크박스가")
check("받침 있음 → 을", j("입력란#을를"), "입력란을")
check("받침 없음 → 를", j("주소#을를"), "주소를")
check("받침 있음 → 과", j("입력란#과와"), "입력란과")
check("받침 없음 → 와", j("체크박스#과와"), "체크박스와")
check("영문으로 끝나면 받침 없음으로 본다", j("button#이가"), "button가")
check("자리 표시가 없으면 그대로", j("그냥 문장"), "그냥 문장")

print("\n[4] 무조건 속성에서 초안을 만들지 않는가 (음성 대조)")
# `role="main"` 에서 명세를 만들면 "뽑아낸 그 속성을 그대로 다시 읽는" 한 지점
# 검사가 되어 아무것도 검증하지 않는다. 규칙 표에 **없어야** 한다.
state_attrs = {a for a, _t, _q in draft.STATE_RULES}
constraint_attrs = {a for a, _p, _t, _q in draft.CONSTRAINT_RULES}
all_attrs = state_attrs | constraint_attrs
for unconditional in ("role", "aria-live", "type", "className", "id"):
    check(f"'{unconditional}' 은 규칙에 없다", unconditional in all_attrs, False)
check("상태 조건부 규칙은 전부 식 값을 받는 속성이다",
      state_attrs, {"disabled", "aria-invalid", "aria-busy", "aria-describedby"})

print("\n[5] 코드 위생 규칙이 초안에 들어오지 않는가 (이것이 TS-028 의 핵심)")
check("미테스트 소스는 기능이 아니다",
      "untested-source" in inspect_mod.NOT_FEATURES, True)
check("미참조 export 는 기능이 아니다",
      "unreferenced-export" in inspect_mod.NOT_FEATURES, True)
check("죽은 스크립트는 기능이 아니다",
      "dead-script" in inspect_mod.NOT_FEATURES, True)
project_mod.clear_cache()
report = inspect_mod.inspect_project(PROJECT)
origins = {d.get("origin") for d in report.draft}
check("초안의 출처가 전부 선언 기반이다", origins <= {"draft:declaration"}, True)
check("초안에 inspect: 출처가 섞이지 않는다",
      any(str(o).startswith("inspect:") for o in origins), False)
# 위생 규칙은 사라지지 않는다 — 검수 보고(checks)에 남아야 한다
kinds = {c.kind for c in report.checks}
check("위생 규칙은 검수 보고에 남는다",
      bool(kinds & {"untested-source", "unreferenced-export"}), True)

print("\n[6] 내용 없는 주제는 질문으로 나가는가")
# "LoginForm 의 입력 검증 규칙" 은 명세가 아니라 **주제**다. 초안으로 내면
# steps 가 빈 채로 features.json 에 들어간다.
check("질문이 있다", len(report.questions) >= 1, True)
check("질문에 결정할 것이 적혀 있다",
      all(q.decision for q in report.questions), True)
check("질문에 초안을 내지 않는 이유가 적혀 있다",
      all("순환" in q.why_not_drafted or "제어 흐름" in q.why_not_drafted
          for q in report.questions), True)
draft_descs = {d["description"] for d in report.draft}
check("'입력 검증 규칙' 이 초안에 없다",
      any("입력 검증 규칙" in d for d in draft_descs), False)
check("'실패 시 동작' 이 초안에 없다",
      any("실패 시 동작" in d for d in draft_descs), False)

print("\n[7] ID — 충돌하지 않고 선언된 형식에 맞는가")
existing = load_features("web_target")
used = {str(f.get("id")) for f in existing}
ids = [d["id"] for d in report.draft]
check("기존 명세와 겹치지 않는다", bool(set(ids) & used), False)
check("초안끼리도 겹치지 않는다", len(set(ids)), len(ids))
cfg_own = config_for("web_target")
rx = cfg_own.id_regex()
check("전부 선언된 id_pattern 에 맞는다",
      all(rx.fullmatch(i) for i in ids), True)
# 자릿수는 **선언된 형식**에서 읽는다 — 기존 ID 에서 추정하면 형식을 위반한다
check("음성 대조: APP-\\d{2} 에서 두 자리를 낸다",
      draft.next_ids([{"id": "APP-01"}, {"id": "APP-02"}], r"APP-\d{2}", 2),
      ["APP-03", "APP-04"])
check("음성 대조: 기존 ID 폭을 따르면 APP-003 이 되어 형식 위반이다",
      bool(re.fullmatch(r"APP-\d{2}", "APP-003")), False)
check("자릿수 선언이 없으면 기존 폭을 따른다",
      draft.next_ids([{"id": "F-0007"}], r"F-\d+", 1), ["F-0008"])
check("기존 명세가 없으면 1 부터", draft.next_ids([], r"F-\d{3}", 2), ["F-001", "F-002"])
check("자릿수를 넘는 번호는 내지 않는다 (형식 위반)",
      draft.next_ids([{"id": "APP-99"}], r"APP-\d{2}", 3), [])

print("\n[8] 픽스처 — 검증 제약 규칙이 실제로 매칭되는가")
# `web_target` 에는 required·minLength·maxLength·pattern 이 **하나도 없다**(실측).
# 규칙만 쓰고 검증하지 않으면 '발견 0건'과 '검사기 고장'을 구별할 수 없다 (TS-016).
project_mod.clear_cache()
fix = "verification/fixtures/vanilla-js"
cfg_fix = config_for(fix)
decls = draft.extract_declarations(fix, cfg_fix)
attrs = {d.attr for d in decls}
for a in ("required", "minLength", "maxLength", "pattern"):
    check(f"픽스처가 '{a}' 규칙을 매칭시킨다", a in attrs, True)
check("상태 조건부도 함께 잡힌다", {"disabled", "aria-invalid"} <= attrs, True)
# 요소를 **라벨 글자**로 부른다 — 변수 이름(`signup-name`)은 사람에게 의미가 없다
names = {d.what for d in decls}
check("라벨 글자로 요소를 부른다", "이름 입력란" in names, True)
check("변수 이름을 그대로 쓰지 않는다", "signup-name" in names, False)
specs_fix = draft.draft_from_declarations(decls, load_features(fix), cfg_fix.id_pattern)
rx_fix = cfg_fix.id_regex()
check("픽스처의 ID 도 선언 형식에 맞는다",
      all(rx_fix.fullmatch(s.id) for s in specs_fix), True)
check("minLength 초안이 숫자를 담는다",
      any("2자 미만" in s.description for s in specs_fix), True)
project_mod.clear_cache()

print("\n[9] 초안이 출처를 지우지 않는가")
# 출처가 지워진 채 features.json 에 섞이면 코드에서 뽑은 명세로 그 코드를
# 검사하게 된다 (TS-013). 모든 항목이 원문·위치·검토 질문을 들고 있어야 한다.
for d in report.draft:
    assert isinstance(d, dict)
check("전부 needs_review 다", all(d["needs_review"] for d in report.draft), True)
check("전부 passes=False 다", any(d["passes"] for d in report.draft), False)
check("전부 원문 출처를 담는다", all(d["source"] for d in report.draft), True)
check("출처에 파일:줄 이 들어 있다",
      all(re.search(r":\d+", s) for d in report.draft for s in d["source"]), True)
check("전부 검토 질문을 담는다", all(d["review_question"] for d in report.draft), True)
check("검토 질문이 한계를 명시한다",
      all("선언 자체가" in d["review_question"] for d in report.draft), True)

print("\n[10] 선언이 없는 프로젝트 — 조용히 거짓을 내지 않는가")
work = Path(tempfile.mkdtemp(prefix="harness-ts028-"))
write(work / "src" / "plain.tsx", "export const A = () => <div>글자</div>;" + NL)
write(work / "features.json", "[]")
write(work / ".harness.json",
      '{"target": ".", "runner": "jest", "source_dirs": ["src"],'
      ' "unit_suffixes": [".test.tsx"], "e2e_suffixes": [".spec.tsx"]}')
project_mod.clear_cache()
cfg_empty = config_for(str(work))
check("뽑을 선언이 없으면 빈 목록", draft.extract_declarations(work, cfg_empty), [])
check("초안도 빈 목록", draft.draft_from_declarations([], [], r"F-\d{3}"), [])
text = draft.format_draft([], [])
check("보고가 '찾지 못했다'고 적는다", "찾지 못했습니다" in text, True)
check("무엇이 필요한지 안내한다", "상태 조건부 선언" in text, True)
project_mod.clear_cache()

print(f"{NL}{'=' * 60}")
print(f"TS-028 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'=' * 60}")
sys.exit(1 if fail else 0)

"""
harness/draft.py
────────────────
**명세 초안 — 사람이 빈 종이를 보지 않게 한다.**

배경 (TS-028):
  `inspect --write-draft` 는 '명세 초안'을 만든다고 선언했지만 실제로는 **검수 발견
  사항을 기능처럼 포장**했다. 실측한 초안 4건 전부:

    F-001  "모든 소스 파일이 최소 한 개의 테스트에서 import 된다"   ← 코드 위생 규칙
    F-002  "export 된 모든 심볼이 어딘가에서 참조된다"               ← 코드 위생 규칙
    F-003  "LoginForm 의 입력 검증 규칙"                            ← 주제, 내용 없음
    F-004  "UserMenu 의 실패 시 동작"                               ← 주제, 내용 없음

  앞의 둘은 **앱의 기능이 아니다.** 사용자가 관찰할 수 있는 행동이 없고 `steps` 를
  채울 수도 없다. `features.json` 에 넣으면 게이트가 기능 아닌 것을 기능으로 센다.
  뒤의 둘은 "명세가 필요한 자리"를 가리키지만 **명세의 내용이 없다.**

  게다가 ID 가 `F-001` 부터 시작해 **기존 명세와 충돌**했다 (`start=1` 고정).

무엇이 순환이고 무엇이 아닌가 — 이 모듈의 유일한 설계 판단:

  순환:     구현의 **제어 흐름**을 읽어 명세로 올린다.
            `if (!email.includes('@')) setError(...)` →
            "이메일에 @ 가 없으면 오류를 표시한다"
            그 구현으로 그 구현을 검사하게 된다 (TS-013).

  불변식:   **선언**을 읽고 **런타임 행동**을 검사한다. 두 지점이 다르다.
            `disabled={loading}` → "로딩 중에는 이 컨트롤이 비활성화된다"
            테스트는 상태를 움직여 DOM 을 읽는다. 선언한 지점과 확인하는 지점이
            다르므로 배선이 끊기면 잡힌다.

  그래서 **상태 조건부 선언만** 쓴다. 무조건 속성은 쓰지 않는다 — 실측:

    disabled={loading}      상태 조건부  → 상태를 움직여 DOM 을 읽는다  (두 지점)
    role="main"             무조건       → 속성이 있는지 읽는다         (한 지점)

  `role`·`aria-live`·`type` 에서 명세를 만들면 "뽑아낸 그 속성을 그대로 다시 읽는"
  것이 되어 아무것도 검증하지 않는다. 제외한다.

정직하게 말해야 하는 한계:
  선언 기반 초안은 **회귀 울타리이고 정확성 증명이 아니다.** `disabled={loading}` 을
  읽어 만든 명세는 "저자가 로딩 중 비활성화를 의도했다"를 전제한다. 저자가 **틀린
  것을 선언했다면** 초안은 그 버그를 명세로 고정한다.

  그래서 모든 초안은 `source` 에 **원문과 위치**를 담고, 사람에게 묻는 문장을
  함께 낸다 — "이 선언 자체가 옳습니까?" 사람이 판단할 것은 빈 종이가 아니라
  **구체적인 한 문장**이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.project import SKIP_DIRS, ProjectConfig, walk_files

#: 선언을 찾는 확장자 — 마크업이 들어 있는 것만
MARKUP_EXTS = (".tsx", ".jsx", ".vue", ".svelte", ".html")

#: 조사 자리 표시 — `#이가` 처럼 쓰고 `_josa` 가 받침을 보고 고른다.
#: 왜 필요한가: 템플릿에 `가` 를 박으면 "제출 버튼**가** 비활성화된다"가 된다(실측).
#: 초안은 사람이 **읽고 판단할** 문장이므로 읽히지 않으면 목적을 잃는다.
_JOSA = re.compile(r"#(이가|을를|은는|과와|으로로)")


def _josa(text: str) -> str:
    """`#이가` 류 자리 표시를 앞 글자의 받침에 맞게 바꾼다.

    한글 음절은 U+AC00..U+D7A3 이고 `(코드 - 0xAC00) % 28` 이 0 이 아니면 받침이 있다.
    한글이 아닌 글자(영문·숫자)로 끝나면 받침 없음으로 본다 — 영문 약어는 읽는
    방식이 갈리므로 어느 쪽을 골라도 틀릴 수 있고, 그 경우는 자연스러운 쪽을 둔다.
    """
    def pick(m: re.Match[str]) -> str:
        pair = m.group(1)
        before = text[:m.start()].rstrip()
        ch = before[-1] if before else ""
        if "가" <= ch <= "힣":
            has_final = (ord(ch) - 0xAC00) % 28 != 0
        else:
            has_final = False
        return pair[0] if has_final else pair[1]

    return _JOSA.sub(pick, text)


#: 상태 조건부 선언 규칙 — (속성, 행동 문장 템플릿, 검토 질문)
#:
#: 전부 **값이 식(expression)인** 속성이다. 값이 리터럴인 속성은 넣지 않는다 —
#: 그것으로 만든 명세는 선언을 읽어 선언을 확인하는 한 지점 검사다.
#:
#: 값은 정규식으로 뽑지 않는다. `aria-describedby={cond ? `${id}-error` : undefined}`
#: 처럼 **중첩 중괄호**가 들어가면 `[^}]` 가 첫 `}` 에서 멈춰 조건식이 잘린다 —
#: 실측에서 `emailError ? \`${emailId` 라는 쓰레기 문장이 나왔다. `_attr_value` 가
#: 중괄호를 세서 뽑는다 (TS-021 과 같은 교훈: 정규식으로 괄호를 맞출 수 없다).
#:
#: 템플릿의 `{cond}` 는 조건식, `{what}` 은 그 요소의 이름이다.
STATE_RULES: tuple[tuple[str, str, str], ...] = (
    ("disabled",
     "{cond} 일 때 {what}#이가 비활성화된다",
     "그때 사용자가 조작할 수 없어야 하는지"),
    ("aria-invalid",
     "{cond} 일 때 {what}#이가 aria-invalid 로 표시된다",
     "오류 상태를 보조 기술에 알려야 하는지"),
    ("aria-busy",
     "{cond} 일 때 {what}#이가 aria-busy 로 표시된다",
     "진행 중임을 보조 기술에 알려야 하는지"),
    ("aria-describedby",
     "{cond} 일 때 {what}에 설명이 연결된다",
     "오류 메시지가 필드와 프로그램적으로 연결되어야 하는지"),
)

#: 검증 제약 — 값이 리터럴이지만 **거부 행동**을 약속하므로 검증 지점이 다르다.
#: `required` 는 "이 속성이 있다"가 아니라 "빈 값이 거부된다"를 약속한다.
#:
#: 이 피험체(`web_target`)에는 **하나도 없다**(실측). 규칙만 쓰고 검증하지 않으면
#: 고장과 '발견 0건'을 구별할 수 없으므로 (TS-016), 픽스처에 심어 고정한다.
CONSTRAINT_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("required",
     r"(?<![\w-])required(?=[\s/>])",
     "{what}#을를 비운 채 제출하면 거부된다",
     "빈 값을 실제로 거부해야 하는지 (경고만 띄우는 것도 선택이다)"),
    ("minLength",
     r"minLength=\{?[\"']?(\d+)",
     "{what}#이가 {cond}자 미만이면 거부된다",
     "그 길이 제한이 맞는지"),
    ("maxLength",
     r"maxLength=\{?[\"']?(\d+)",
     "{what}#이가 {cond}자를 넘으면 입력되지 않는다",
     "그 길이 제한이 맞는지"),
    ("pattern",
     r"pattern=\{?[\"']([^\"']{1,60})",
     "{what}#이가 지정한 형식에 맞지 않으면 거부된다",
     "그 형식 규칙이 맞는지"),
)


def _attr_value(text: str, start: int) -> tuple[str, int] | None:
    """`attr={` 직후부터 **중괄호를 세어** 값을 뽑는다. (값, 끝 인덱스).

    정규식으로 할 수 없다 — `{cond ? `${id}-error` : undefined}` 는 중첩 중괄호를
    갖는다. 문자열·템플릿 리터럴 안의 중괄호는 세지 않는다.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0           # JSX 식의 중괄호 깊이
    interp = 0          # 템플릿 보간 `${…}` 의 깊이 — depth 와 **따로** 센다
    quotes: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        cur = quotes[-1] if quotes else ""
        if cur:
            if ch == "\\":
                i += 2
                continue
            if ch == cur:
                quotes.pop()
            elif cur == "`" and ch == "$" and text[i + 1:i + 2] == "{":
                interp += 1
                i += 2
                continue
            elif cur == "`" and ch == "}" and interp > 0:
                interp -= 1
        elif ch in "\"'`":
            quotes.append(ch)
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None


def _condition_of(expr: str) -> str:
    """식에서 **조건**만 남긴다.

    `emailError ? X : undefined` 의 조건은 `emailError` 다. 삼항 전체를 조건으로
    쓰면 "`emailError ? X : undefined` 일 때" 라는 읽을 수 없는 문장이 나온다.
    `!!x` 는 `x` 로 줄인다 — 이중 부정은 참/거짓 변환이므로 의미가 같다.
    번역은 하지 않는다. `emailError` 가 무엇을 뜻하는지는 코드가 알고 나는 모른다.
    """
    e = re.sub(r"\s+", " ", expr.strip())
    # 최상위 `?` 앞까지 (문자열·중괄호 안의 `?` 는 건너뛴다)
    depth = 0
    quote = ""
    for i, ch in enumerate(e):
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif ch == "?" and depth == 0:
            e = e[:i].strip()
            break
    while e.startswith("!!"):
        e = e[2:].strip()
    return e


@dataclass
class Declaration:
    """소스가 선언한 사실 하나 — 어디에서 읽었는지를 함께 담는다."""

    attr: str
    cond: str            # 조건식 또는 제약값
    what: str            # 요소 이름 (id / name / 태그)
    file: str
    line: int
    text: str            # 원문 한 줄 (사람이 선언 자체를 판단할 근거)
    rule_kind: str       # 'state' | 'constraint'


@dataclass
class DraftSpec:
    """명세 **초안** 한 건. `features.json` 과 같은 모양이되 출처가 박혀 있다."""

    id: str
    description: str
    steps: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    review_question: str = ""

    def to_feature(self) -> dict[str, Any]:
        """`features.json` 항목 모양. `origin`·`needs_review` 를 지우지 않는다 —
        출처가 지워진 채 섞이면 코드에서 뽑은 명세로 그 코드를 검사하게 된다."""
        return {
            "id": self.id,
            "description": self.description,
            "passes": False,
            "steps": self.steps,
            "origin": "draft:declaration",
            "needs_review": True,
            "source": self.source,
            "review_question": self.review_question,
        }


@dataclass
class DraftQuestion:
    """명세가 필요하지만 **내용이 구현에만** 있는 자리. 초안이 아니라 질문이다.

    명세로 내지 않는 이유: 구현의 제어 흐름을 읽어 명세로 올리면 순환이다
    (TS-013). 사람이 답해야 하는 **결정**을 구체적으로 적어 넘긴다.
    """

    topic: str
    where: str
    decision: str        # 사람이 내려야 하는 결정
    why_not_drafted: str


# ── 선언 추출 ────────────────────────────────────────────────────────────────

#: `<label htmlFor={x}>라벨 글자</label>` — 사람이 보는 이름의 출처
_LABEL_RE = re.compile(
    r"<label[^>]*htmlFor=\{?[\"']?([\w.-]+)[\"']?\}?[^>]*>(.*?)</label>",
    re.DOTALL)


def _labels_in(text: str) -> dict[str, str]:
    """`htmlFor` → 라벨 글자. 요소를 **사람이 보는 이름**으로 부르기 위해서다.

    변수 이름(`emailId`)으로 명세를 쓰면 "emailId 가 비활성화된다"가 되어 읽는
    사람에게 아무 의미가 없다 (실측). 라벨은 사용자가 실제로 보는 글자다.
    """
    out: dict[str, str] = {}
    for m in _LABEL_RE.finditer(text):
        inner = re.sub(r"<[^>]+>", "", m.group(2))        # 중첩 태그 제거
        inner = re.sub(r"\{[^}]*\}", "", inner)           # JSX 표현식 제거
        label = re.sub(r"\s+", " ", inner).strip(" *\t\n")
        if label:
            out[m.group(1)] = label
    return out


def _element_name(line: str, before: str, labels: dict[str, str]) -> str:
    """그 선언이 붙은 요소를 **사람이 읽는 이름**으로.

    우선순위: 라벨 글자 → `name=` → 태그+type → 태그. JSX 속성은 여러 줄에
    걸치므로 같은 줄에 없으면 **위쪽 열린 태그**에서 찾는다.
    """
    tail = before[-800:]
    opens = list(re.finditer(r"<([A-Za-z][\w.]*)", tail))
    chunk = tail[opens[-1].start():] + line if opens else line
    tag = opens[-1].group(1) if opens else ""

    for pat in (r'id=\{?[\"\']?([\w.-]+)', r'htmlFor=\{?[\"\']?([\w.-]+)'):
        m = re.search(pat, chunk)
        if m and m.group(1) in labels:
            return f"{labels[m.group(1)]} 입력란" if tag == "input" else labels[m.group(1)]
    m = re.search(r'name=[\"\']([\w-]+)', chunk)
    if m:
        return m.group(1)
    m = re.search(r'type=[\"\'](\w+)', chunk)
    if m:
        kind = {"submit": "제출 버튼", "button": "버튼", "email": "이메일 입력란",
                "password": "비밀번호 입력란", "checkbox": "체크박스"}.get(m.group(1))
        if kind:
            return kind
    return tag or "해당 요소"


def extract_declarations(project_root: str | Path,
                         cfg: ProjectConfig) -> list[Declaration]:
    """상태 조건부 선언과 검증 제약을 모은다. **제어 흐름은 보지 않는다.**"""
    root = Path(project_root).resolve()
    out: list[Declaration] = []
    for d in cfg.source_dirs:
        base = (root / d).resolve()
        if not base.is_dir():
            continue
        for p in sorted(walk_files(base, SKIP_DIRS, MARKUP_EXTS)):
            if cfg.is_test_file(p.name):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            lines = text.split("\n")
            labels = _labels_in(text)

            def add(attr: str, cond: str, at: int, kind: str) -> None:
                lineno = text[:at].count("\n") + 1
                out.append(Declaration(
                    attr=attr, cond=cond,
                    what=_element_name(lines[lineno - 1], text[:at], labels),
                    file=rel, line=lineno,
                    text=lines[lineno - 1].strip()[:120], rule_kind=kind,
                ))

            # 상태 조건부 — 값을 중괄호를 세어 뽑는다
            for attr, _tmpl, _q in STATE_RULES:
                for m in re.finditer(rf"(?<![\w-]){re.escape(attr)}=", text):
                    got = _attr_value(text, m.end())
                    if got is None:
                        continue        # 값이 리터럴이다 — 상태 조건부가 아니다
                    cond = _condition_of(got[0])
                    if cond:
                        add(attr, cond, m.start(), "state")
            # 검증 제약 — 값이 리터럴이거나 값이 없다
            for attr, pat, _tmpl, _q in CONSTRAINT_RULES:
                for m in re.finditer(pat, text):
                    add(attr, m.group(1) if m.groups() else "", m.start(), "constraint")
    return out


# ── ID 배정 ──────────────────────────────────────────────────────────────────

def next_ids(existing: list[dict[str, Any]], id_pattern: str,
             count: int) -> list[str]:
    """기존 명세와 **충돌하지 않고** 선언된 ID 형식에 **맞는** ID 를 count 개 만든다.

    두 가지가 실측으로 틀렸다 (TS-028):

      1. 이전 구현은 `start=1` 고정으로 `F-001` 부터 냈고 그것은 이미 쓰이고 있는
         번호였다. 초안을 옮기면 명세가 덮이거나 중복된다.
      2. 자릿수를 기존 ID 에서만 추정해 `APP-01`·`APP-02` 를 보고 `APP-003` 을 냈다.
         픽스처는 `id_pattern: "APP-\\d{2}"` 를 선언하므로 **세 자리는 형식 위반**이고
         `cli tags` 가 거부한다. 자릿수는 **선언된 형식**에서 읽어야 한다.

    선언이 자릿수를 고정하지 않으면(`\\d+`) 기존 ID 의 폭을 따르고, 기존 ID 도
    없으면 3 자리를 쓴다.
    """
    prefix_match = re.match(r"([A-Za-z]+)[^A-Za-z0-9\\]*", id_pattern)
    prefix = (prefix_match.group(1) + "-") if prefix_match else "F-"

    # 선언된 형식이 자릿수를 고정하는가 — `\d{2}` / `\d{3}`
    declared = re.search(r"\\d\{(\d+)\}", id_pattern)

    used: set[int] = set()
    observed = 0
    for f in existing:
        m = re.match(rf"{re.escape(prefix)}(\d+)$", str(f.get("id", "")))
        if m:
            used.add(int(m.group(1)))
            observed = max(observed, len(m.group(1)))
    width = int(declared.group(1)) if declared else (observed or 3)

    out: list[str] = []
    n = max(used) + 1 if used else 1
    # 자릿수를 넘는 번호는 형식 위반이므로 내지 않는다 (`APP-\d{2}` 에서 100 번째)
    limit = 10 ** width
    while len(out) < count and n < limit:
        if n not in used:
            out.append(f"{prefix}{n:0{width}d}")
        n += 1
    return out


# ── 초안 만들기 ──────────────────────────────────────────────────────────────

def _template_for(attr: str) -> tuple[str, str]:
    for a, tmpl, q in STATE_RULES:
        if a == attr:
            return tmpl, q
    for a, _pat, tmpl, q in CONSTRAINT_RULES:
        if a == attr:
            return tmpl, q
    return "{what}의 {cond} 동작", "이 동작이 맞는지"


def draft_from_declarations(decls: list[Declaration],
                            existing: list[dict[str, Any]],
                            id_pattern: str) -> list[DraftSpec]:
    """선언을 묶어 명세 초안으로. **파일+요소+속성** 단위로 하나씩 낸다.

    같은 조건식이 여러 요소에 붙어 있으면(`disabled={loading}` 이 입력 2개와
    버튼 1개에) 하나의 명세에 `steps` 로 담는다 — 그것이 하나의 행동이다.
    """
    # (파일, 속성, 조건) 으로 묶는다. 요소는 steps 가 된다.
    groups: dict[tuple[str, str, str], list[Declaration]] = {}
    for d in decls:
        groups.setdefault((d.file, d.attr, d.cond), []).append(d)

    # 선언이 나온 **줄 번호 순**으로 낸다 — 파일을 위에서 아래로 읽는 순서가
    # 사람이 검토하는 순서다. 묶음 키(속성 이름) 순으로 내면 aria-busy 가 먼저 나온다.
    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[0][0], min(d.line for d in kv[1])))
    ids = next_ids(existing, id_pattern, len(groups))
    out: list[DraftSpec] = []
    for fid, ((f, attr, cond), items) in zip(ids, ordered):
        tmpl, question = _template_for(attr)
        whats = sorted({d.what for d in items})
        # 복수 주어는 이름을 그대로 나열한다 — "2개 요소" 라고 쓰면 무엇인지 모른다.
        # 나열 조사도 받침을 따른다 (`입력란과` / `버튼과` vs `체크박스와`).
        subject = whats[0] if len(whats) == 1 else "#과와 ".join(whats)
        desc = _josa(tmpl.format(cond=cond, what=subject))
        steps = ([_josa(tmpl.format(cond=cond, what=w)) for w in whats]
                 if len(whats) > 1 else [])
        out.append(DraftSpec(
            id=fid,
            description=desc,
            steps=steps,
            source=[f"{d.file}:{d.line}  {d.text}" for d in items],
            review_question=(
                f"{question} — 이 문장은 위 **선언을 읽어** 만들었습니다. "
                "선언과 런타임 동작이 어긋나면 테스트가 잡지만, **선언 자체가 "
                "틀렸다면** 이 명세는 그 오류를 고정합니다. 원문을 보고 판단하십시오."
            ),
        ))
    return out


def format_draft(specs: list[DraftSpec], questions: list[DraftQuestion]) -> str:
    """사람이 읽는 초안 보고."""
    bar = "=" * 72
    lines = [
        bar,
        "명세 초안 — 빈 종이 대신 **구체적인 문장**을 드립니다",
        bar,
        "",
        "  초안은 `features.json` 이 아닙니다. 사람이 읽고 옮겨야 효력이 생깁니다.",
        "  각 항목에는 **어느 선언을 읽어 만들었는지**가 원문과 함께 붙어 있습니다 —",
        "  선언 자체가 틀렸다면 초안도 틀리므로, 그 판단은 사람이 해야 합니다.",
        "",
        f"  초안 {len(specs)}건 · 질문 {len(questions)}건",
    ]

    if specs:
        lines += ["", "  " + "-" * 68, "  초안 — 선언에서 뽑았습니다 (검증 지점이 다릅니다)", ""]
        for s in specs:
            lines.append(f"  {s.id}  {s.description}")
            for st in s.steps:
                lines.append(f"        · {st}")
            for src in s.source:
                lines.append(f"        ← {src}")
            lines.append(f"        ? {s.review_question}")
            lines.append("")

    if questions:
        lines += ["  " + "-" * 68,
                  "  질문 — 명세가 필요하지만 **내용이 구현에만** 있습니다", ""]
        for q in questions:
            lines.append(f"  · {q.topic}  ({q.where})")
            lines.append(f"      결정할 것: {q.decision}")
            lines.append(f"      초안을 내지 않는 이유: {q.why_not_drafted}")
            lines.append("")

    if not specs and not questions:
        lines += ["", "  초안을 만들 선언을 찾지 못했습니다.",
                  "  상태 조건부 선언(`disabled={...}`, `aria-invalid={...}`)이나",
                  "  검증 제약(`required`, `minLength`)이 있는 마크업이 필요합니다."]

    lines += [
        "",
        "  " + "-" * 68,
        "  한계: 선언 기반 초안은 **회귀 울타리**이고 정확성 증명이 아닙니다.",
        "  저자가 틀린 것을 선언했다면 초안은 그 버그를 명세로 고정합니다 (TS-028).",
        bar,
    ]
    return "\n".join(lines)

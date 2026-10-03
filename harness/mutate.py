"""
harness/mutate.py
─────────────────
증거가 **실제로 무는가** 를 측정한다 — 돌연변이 검사.

배경 (TS-016):
  TS-008 의 게이트는 "기능 ID 를 인용하는 통과 테스트"를 요구하고,
  TS-016 의 커버리지 요구는 "그 테스트가 소스를 실행한다"까지 보장한다.
  그래도 남는 구멍이 있다 — **소스를 실행하지만 아무것도 단정하지 않는 테스트.**
  커버리지는 통과하고 결함은 놓친다.

  그걸 묻는 유일한 방법은 결함을 **일부러 넣어보는 것**이다.
  구현을 perturb 했을 때 테스트가 실패하지 않으면, 그 테스트는 장식이다.

왜 게이트가 아니라 측정인가:
  변이 하나당 타입 검사(약 5초) + 범위 테스트(약 3초)가 든다. `mark` 마다 돌리면
  기능 하나를 기록하는 데 분 단위가 걸려 작업이 멈춘다. 그래서 **on-demand 명령**으로 둔다.
  게이트는 빠르고 정확한 것만 담는다 (태그 + 커버리지).

안전 설계:
  - 변이는 **원본을 백업한 뒤** 적용하고, 성공·실패·예외와 무관하게 `finally` 에서 복원한다.
  - 적용 후 `tsc --noEmit` 으로 **구문/타입이 유효한지 먼저 확인**한다.
    깨진 변이는 "테스트가 잡았다"로 오계산하면 안 되므로 폐기한다(invalid).
  - 변이 대상은 해당 기능의 증거가 실제로 실행하는 파일로 한정한다
    (TS-016 의 커버리지 결과를 그대로 쓴다).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.verify import (
    coverage_for_feature,
    feature_name_pattern,
    runner_for,
    tagged_test_files,
)

#: 변이 규칙 — (이름, 찾을 정규식, 바꿀 문자열).
#: 전부 **구문을 유지하는** 치환이다. 그래도 타입 검사로 다시 확인한다.
#:
#: `None` 치환은 전용 적용 함수가 처리한다 (정규식으로 괄호를 균형 맞출 수 없다).
MUTATIONS: tuple[tuple[str, str, str | None], ...] = (
    ("비교 반전 (=== → !==)", r"===", "!=="),
    ("비교 반전 (!== → ===)", r"!==", "==="),
    ("논리 반전 (&& → ||)", r"&&", "||"),
    # TS-021: 이전 패턴 `(?<![<>=!])>(?![=>])` 는 **190곳**에 매칭됐고 그중 진짜 비교는
    # **3곳**뿐이었다. 나머지는 JSX 태그(108곳)와 제네릭(32곳)이어서 치환하면
    # `React.FC<Props>` 가 `React.FC<Props>=` 가 되는 **구문 파괴**였다.
    # 변이가 테스트를 시험하는 게 아니라 컴파일러를 시험했고, '폐기' 집계가
    # 그 사실을 가렸다. 공백을 양쪽에 요구하면 `a > b` 만 남는다 —
    # `=>` 는 `>` 앞이 `=` 이므로 자동으로 제외된다.
    ("경계 이동 (a > b → a >= b)", r"(?<=\s)>(?=\s)", ">="),
    ("불리언 반전 (true → false)", r"\btrue\b", "false"),
    # TS-021: 이전 패턴 `if \(([^)]{1,80})\)` 는 중첩 괄호에서 깨졌다 —
    # `if (!re.test(email))` → `if (false))` 로 괄호가 남았다 (26곳 중 5곳).
    # 정규식은 괄호 균형을 맞출 수 없으므로 전용 적용 함수로 옮겼다.
    ("조건 무력화 (if (X) → if (false))", r"\bif\s*\(", None),
)

#: 파일 하나에서 시도할 최대 변이 수 — 시간 때문에 제한한다
MAX_MUTANTS_PER_FILE = 3

#: 컬렉션 멤버 제거 변이의 상한 (TS-022). 선언된 컬렉션은 보통 소수이므로 따로 둔다.
MAX_COLLECTION_MUTANTS = 4


def select_spread(candidates: list[Any], budget: int) -> list[Any]:
    """후보에서 **고르게 퍼진** 부분집합을 고른다 (TS-022).

    왜 '첫 번째'를 쓰지 않는가 — 실측:
      이전 구현은 규칙당 `lines[0]` 만 썼다. `LoginForm.tsx` 는 변이 가능 지점이
      19곳인데 시도되는 것은 3곳뿐이었다. 32번 줄이 항상 이기므로 55·56번 줄 —
      `safeRedirectTarget` 의 오픈 리다이렉트 가드, 즉 TS-011 의 수정 — 은
      **한 번도 변이 검사를 받지 못했다.**

      (TS-022 는 이 19곳이 '전부 실행되는 줄'이라고 적었다. **틀린 측정이었다** —
      실제로는 2곳만 실행된다. TS-026 이 정정했고, 그래서 지금은 `_candidate_lines`
      가 실행된 줄로 먼저 걸러낸 뒤 이 함수가 퍼뜨린다.)

      예산이 한정된 것 자체는 문제가 아니다. 문제는 **항상 같은 곳**을 고르는 것이다.
      무작위가 아니라 등간격을 쓰는 이유: 재현 가능해야 회귀로 고정할 수 있다.
    """
    if budget <= 0 or not candidates:
        return []
    if len(candidates) <= budget:
        return list(candidates)
    step = (len(candidates) - 1) / (budget - 1) if budget > 1 else 0
    picked = [candidates[round(i * step)] for i in range(budget)]
    # round 이 같은 인덱스를 두 번 고를 수 있다 — 중복을 제거하고 뒤에서 채운다
    out: list[Any] = []
    for c in picked:
        if c not in out:
            out.append(c)
    for c in candidates:
        if len(out) >= budget:
            break
        if c not in out:
            out.append(c)
    return out[:budget]


@dataclass
class MutantResult:
    rule: str
    file: str
    line: int
    status: str      # 'killed' | 'survived' | 'invalid'
    detail: str = ""


def _typechecks(project_root: str) -> bool:
    """변이가 구문·타입상 유효한지 — 깨진 변이를 '잡았다'로 세지 않기 위해.

    정적 검사 커맨드가 선언되지 않았으면 True 를 돌려 **건너뛴다.** 모든 변이를
    '무효'로 처리하면 점수가 사라지기 때문이다. 대신 `skipped_typecheck()` 가
    그 사실을 보고서에 노출해 점수의 과대평가 가능성을 명시한다.
    """
    return runner_for(project_root).typechecks()[0]


def skipped_typecheck(project_root: str) -> str:
    """정적 검사를 건너뛴 사유. 빈 문자열이면 실제로 검사했다."""
    try:
        return runner_for(project_root).typechecks()[1]
    except ValueError as exc:
        return str(exc)


def _tests_fail(project_root: str, feature_id: str, test_files: list[str]) -> bool:
    """해당 기능의 태그 테스트가 **실패하는가** (= 변이를 잡았는가).

    런너에 위임한다. 실행 자체가 불가능하면(런너 없음) False — '잡지 못했다'로
    본다. 실행 못 한 것을 '잡았다'로 세면 점수가 거짓으로 올라간다.
    """
    try:
        runner = runner_for(project_root)
    except ValueError:
        return False
    if runner.launcher() is None:
        return False
    code, _ = runner.run_scoped(test_files, feature_name_pattern(feature_id))
    return code not in (0, None)


def _candidate_lines(text: str, pattern: str,
                     executed: set[int] | None = None) -> list[int]:
    """해당 규칙이 적용 가능한 줄 번호. 주석·import 줄은 제외한다.

    `executed` 가 주어지면 **그 줄만** 돌려준다 (TS-026). 왜 필요한가 — 실측:

      커버리지는 **파일**을 고르는 데만 쓰였다. 그래서 17줄 실행된 파일의 미실행
      줄에 변이가 들어갔고, 그 변이는 어떤 테스트도 지나가지 않으므로 **반드시
      생존**했다. 생존은 점수의 분모에 들어간다 → 점수가 틀린 값으로 낮아진다.

      `LoginForm.tsx` 의 후보 18곳 중 실행되는 것은 **2곳**이었다. 나머지 16곳은
      '테스트가 약하다'가 아니라 '테스트가 거기까지 가지 않는다'인데, 보고서는
      전자로 읽히게 적고 있었다 — TS-023 과 같은 종류의 오독을 측정기가 직접
      만들어내고 있었다.

      이것은 TS-022 의 부작용이기도 하다. 표본을 고르게 퍼뜨린 뒤로 미실행 줄까지
      균등하게 뽑히기 시작했다. TS-022 는 **닿는 범위**를 넓혔고, 닿아야 할 곳과
      닿아도 의미 없는 곳을 가르지 않았다.

    `None` 은 '줄 지도를 모른다'이므로 필터하지 않는다 — 측정 실패를 '대상 없음'으로
    바꾸지 않기 위해서다. 호출자가 그 사실을 보고서에 적는다.
    """
    hits = []
    for i, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*", "import ", "export type")):
            continue
        if executed is not None and i not in executed:
            continue
        if re.search(pattern, line):
            hits.append(i)
    return hits


def drop_member(text: str, collection: str, member: str) -> str | None:
    """앱이 선언한 컬렉션에서 멤버 하나를 제거한다 (TS-022).

    왜 이 연산자가 필요한가 — 실측:
      `routes.ts` 는 F-005 의 증거가 6줄 실행하는데 기존 연산자의 변이 지점이
      **0곳**이었다. 배열 선언에는 비교·논리·조건이 없다. 그래서 다음을 주입하지
      못했다 — `PROTECTED_PATHS` 에서 경로를 지우는 것, 즉 **TS-013 의 버그 모양**
      그 자체다.

      실험 결과 보호 경로 4개 중 **3개를 지워도 전체 스위트가 통과**했다
      (51 → 49 통과, 실패 0). `test.each(PROTECTED_PATHS)` 는 목록이 줄면
      **덜 돌 뿐**이기 때문이다. `/dashboard` 만 잡혔고 그 이유는
      `expect(PROTECTED_PATHS).toContain('/dashboard')` 로 이름이 박혀 있어서였다.

      기존 사다리 네 칸(태그·커버리지·독립성·돌연변이)이 **전부 통과하는 동안**
      명세가 보호를 요구하는 경로가 사라진다.

    선언 범위 안에서만 제거한다 — 같은 문자열이 파일 다른 곳에 있어도 건드리지 않는다.
    제거할 수 없으면(선언을 찾지 못함, 멤버가 없음) `None`.
    """
    from harness.independence import _COLLECTION_RE

    for m in _COLLECTION_RE.finditer(text):
        if m.group(1) != collection:
            continue
        body = m.group(2)
        body_start = m.start(2)
        # 멤버 리터럴과 **뒤따르는 쉼표**(없으면 앞의 쉼표)를 함께 지운다
        pat = re.compile(rf"""(\s*)(['"]){re.escape(member)}\2(\s*,)?""")
        hit = pat.search(body)
        if hit is None:
            return None
        if hit.group(3) is None:
            # 마지막 멤버 — 앞쪽 쉼표를 걷어내 `['a',]` 가 되지 않게 한다
            new_body = body[:hit.start()].rstrip().rstrip(",") + body[hit.end():]
        else:
            new_body = body[:hit.start()] + body[hit.end():]
        if new_body == body:
            return None
        return text[:body_start] + new_body + text[body_start + len(body):]
    return None


#: 멤버가 명세에 **경로/식별자로** 등장하는지 판정할 때의 경계 문자 집합.
#: ASCII 로 한정하는 이유: 한국어 명세는 `/dashboard에 접속한다` 처럼 경로 뒤에 한글이
#: 붙는다. `\w` 를 쓰면 한글이 단어 문자라서 경계로 인정되지 않아 전부 미매칭된다(실측).
_MEMBER_BOUNDARY = r"(?![A-Za-z0-9_/-])"


def spec_text(project_root: str, feature_id: str) -> str:
    """기능 하나의 명세 전문 (설명 + 단계). 찾지 못하면 빈 문자열."""
    from harness.verify import find_index, load_features

    try:
        features = load_features(project_root)
    except (OSError, ValueError):
        return ""
    idx = find_index(features, feature_id)
    if idx < 0:
        return ""
    f = features[idx]
    return " ".join([str(f.get("description", "")), *(str(s) for s in f.get("steps") or [])])


def spec_names(member: str, spec: str) -> bool:
    """명세가 이 멤버를 **지목하는가** (TS-023).

    왜 필요한가 — 실측:
      `PROTECTED_PATHS` 의 멤버를 지웠을 때 `/`, `/profile`, `/settings` 가 생존했다.
      그래서 "테스트가 약하다"고 읽고 단정을 추가하려 했는데, 명세를 보니 F-005 는
      **`/dashboard` 만 지목**한다. 나머지 3개는 명세가 요구하지 않는다.

      그 3개를 테스트로 고정하면 **명세에 없는 것을 단정하는 테스트**가 된다 —
      TS-014 가 '측정 도구 오류'로 분류하고 고쳤던 바로 그것이고, 현재 구현을
      명세로 승격시키는 순환이다.

      따라서 생존은 두 종류다:
        명세가 지목함  → **증거의 진짜 공백** (요구되는데 고정되지 않았다)
        명세에 없음    → **명세의 공백** (앱이 명세를 넘어 구현했다. 테스트의 잘못이 아니다)

    경계 판정은 사실이다 — 멤버 문자열이 경로 경계와 함께 명세에 있는가.
    `?redirect=/dashboard` 가 멤버 `/` 에 오매칭되지 않는 것을 실측으로 확인했다.
    """
    if not member or not spec:
        return False
    return bool(re.search(re.escape(member) + _MEMBER_BOUNDARY, spec))


def _member_line(text: str, collection: str, member: str) -> int:
    """멤버가 **선언 안에서** 몇 번째 줄에 있는가.

    파일 전체에서 첫 occurrence 를 찾으면 안 된다 — `'/'` 같은 짧은 멤버는 주석의
    경로 문자열(`web_target/src/routes.ts`)에 먼저 걸려 1번 줄이 나온다(실측).
    """
    from harness.independence import _COLLECTION_RE

    for m in _COLLECTION_RE.finditer(text):
        if m.group(1) != collection:
            continue
        body, body_start = m.group(2), m.start(2)
        hit = re.search(rf"""(['"]){re.escape(member)}\1""", body)
        if hit is None:
            return text[:body_start].count("\n") + 1
        return text[:body_start + hit.start()].count("\n") + 1
    return 0


def collection_candidates(project_root: str, covered_files: list[str]) -> list[tuple]:
    """증거가 실행하는 파일에 선언된 컬렉션의 (컬렉션, 파일, 멤버) 후보."""
    from harness.independence import declared_collections

    names = {Path(f).name for f in covered_files}
    out: list[tuple] = []
    for coll in declared_collections(project_root):
        if Path(coll.declared_in).name not in names:
            continue
        for member in coll.members:
            out.append((coll.name, coll.declared_in, member))
    return out


def neutralize_condition(line: str) -> str | None:
    """`if (…)` 의 조건을 `false` 로 바꾼다 — **괄호를 세어** 균형을 지킨다.

    정규식으로 할 수 없는 이유 (TS-021): `if \\(([^)]{1,80})\\)` 는 첫 `)` 에서
    멈추므로 `if (!re.test(email))` 를 `if (false))` 로 만들어 괄호를 남겼다.
    매칭 26곳 중 5곳이 그랬다. 문자를 세는 것이 정확하고 더 짧다.

    문자열 리터럴 안의 괄호도 건너뛴다 — `if (s === "a)b")` 같은 경우.
    닫는 괄호를 찾지 못하면(줄이 바뀌는 조건) `None` 을 돌려 건너뛴다.
    """
    m = re.search(r"\bif\s*\(", line)
    if m is None:
        return None
    open_at = m.end() - 1               # '(' 의 위치
    depth = 0
    quote: str | None = None
    for i in range(open_at, len(line)):
        ch = line[i]
        if quote is not None:
            if ch == "\\":
                continue
            if ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return line[:open_at] + "(false)" + line[i + 1:]
    return None                        # 조건이 여러 줄에 걸쳐 있다 — 건드리지 않는다


def mutate_feature(
    project_root: str,
    feature_id: str,
    max_files: int = 2,
    max_per_file: int | None = None,
    max_collection: int | None = None,
) -> dict[str, Any]:
    """기능 하나의 증거에 대해 돌연변이 점수를 측정한다.

    Args:
        max_files:      줄 변이 대상 파일 수 (커버리지 상위 N개)
        max_per_file:   파일당 줄 변이 수. None 이면 MAX_MUTANTS_PER_FILE.
                        후보가 예산을 넘으면 **고르게 퍼뜨려** 고른다 — 첫 번째만
                        고르면 파일 앞머리만 영원히 검사된다 (TS-022).
        max_collection: 컬렉션 멤버 제거 변이 수. None 이면 MAX_COLLECTION_MUTANTS.

    Returns:
        {feature, mutants: [...], killed, survived, invalid, score, sources, sites}
        score = killed / (killed + survived) — invalid 는 분모에서 제외한다.
        sites 는 **후보 총수**다 — 예산 때문에 몇 개를 건너뛰었는지 보이게 한다.
    """
    budget_file = MAX_MUTANTS_PER_FILE if max_per_file is None else max_per_file
    budget_coll = MAX_COLLECTION_MUTANTS if max_collection is None else max_collection
    test_files = tagged_test_files(project_root, feature_id)
    if not test_files:
        return {"error": f"{feature_id} 태그가 있는 단위 테스트가 없습니다."}

    cov, diag = coverage_for_feature(project_root, feature_id, top_n=10, test_files=test_files)
    if cov is None:
        return {"error": diag}
    if not cov["sources"]:
        return {"error": f"{feature_id} 의 증거가 소스를 실행하지 않습니다 (측정 불가)."}

    # 증거가 실제로 실행하는 파일만 변이 대상으로 삼는다
    root = Path(project_root).resolve()
    targets: list[Path] = []
    for entry in cov["sources"][:max_files]:
        name = entry.split(" (")[0]
        found = [p for p in root.rglob(name) if "node_modules" not in p.parts]
        if found:
            targets.append(found[0])

    # 실행된 줄 지도 — 변이 지점을 **줄 단위로** 제한하는 데 쓴다 (TS-026).
    # 파일 단위로만 제한하면 미실행 줄에 변이가 들어가 생존이 보장된다.
    line_map: dict[str, set[int]] = cov.get("executed_lines") or {}
    unmapped: list[str] = []            # 줄 지도를 못 얻은 파일 — 보고서에 적는다
    skipped_unexecuted = 0              # 미실행이라 제외한 변이 지점 **줄 수**
    reached_lines = 0                   # 증거가 닿는 변이 지점 **줄 수**

    results: list[MutantResult] = []
    site_total = 0                      # 후보 총수 — 예산 때문에 건너뛴 수가 보이게 한다
    for target in targets:
        original = target.read_text(encoding="utf-8")
        rel = str(target.relative_to(root)).replace("\\", "/")
        applied = 0
        backup = tempfile.mkdtemp(prefix="harness-mut-")
        backup_file = Path(backup) / target.name
        backup_file.write_text(original, encoding="utf-8")

        # `None` = 줄 지도를 모른다(필터하지 않고 사실을 기록), `set()` = 실행된 줄이
        # 없다(변이할 자리가 없다). 둘을 섞으면 측정 실패가 '대상 없음'으로 위장된다.
        executed = line_map.get(target.name)
        if executed is None:
            unmapped.append(rel)

        # 후보를 **전부 모은 뒤** 고르게 퍼뜨려 고른다 (TS-022).
        # 이전 구현은 규칙 순서대로 돌며 각 규칙의 `lines[0]` 만 썼다 — 그래서
        # 파일 앞머리의 같은 줄만 영원히 검사되고, `LoginForm.tsx` 의 19개 지점 중
        # 16개(오픈 리다이렉트 가드 포함)가 한 번도 검사되지 않았다.
        candidates = [
            (lineno, rule, pattern, replacement)
            for rule, pattern, replacement in MUTATIONS
            for lineno in _candidate_lines(original, pattern, executed)
        ]
        if executed is not None:
            # 제외된 수를 센다 — '후보가 적다'와 '테스트가 약하다'를 가르는 수치다.
            # **줄 수로 센다.** 한 줄에 규칙 두 개가 걸리면 변이는 2개지만 지점은
            # 1곳이다. 도달률을 '변이 수 / 줄 수' 로 섞으면 단위가 다른 값을 나눠
            # 의미 없는 비율이 나온다 — 실측에서 2개+1줄을 '3곳'으로 적고 있었다.
            all_sites = {
                lineno
                for rule, pattern, replacement in MUTATIONS
                for lineno in _candidate_lines(original, pattern)
            }
            skipped_unexecuted += len(all_sites - executed)
            reached_lines += len(all_sites & executed)
        candidates.sort(key=lambda c: (c[0], c[1]))
        site_total += len(candidates)
        try:
            for lineno, rule, pattern, replacement in select_spread(candidates, budget_file):
                if applied >= budget_file:
                    break
                src = original.split("\n")
                if replacement is None:
                    mutated_line = neutralize_condition(src[lineno - 1])
                    if mutated_line is None:
                        continue        # 괄호가 줄을 넘는다 — 건드리지 않는다
                else:
                    mutated_line = re.sub(pattern, replacement, src[lineno - 1], count=1)
                if mutated_line == src[lineno - 1]:
                    continue            # 아무것도 바뀌지 않았다 — 변이가 아니다
                src[lineno - 1] = mutated_line
                target.write_text("\n".join(src), encoding="utf-8")
                applied += 1
                try:
                    # 검사 순서가 비용을 결정한다 (TS-021).
                    #
                    # 실측(웜 캐시): 범위 jest 2.7초, tsc 1.9초.
                    # jest 를 **먼저** 돌리면 통과한 변이(=생존)는 tsc 를 건너뛸 수 있다 —
                    # 통과했다는 것은 컴파일됐다는 뜻이므로 유효성을 다시 물을 필요가 없다.
                    # tsc 는 jest 가 **실패했을 때만** 필요하다: '테스트가 잡았다'와
                    # '애초에 컴파일되지 않았다'를 구분하기 위해서다.
                    failed = _tests_fail(project_root, feature_id, test_files)
                    if not failed:
                        results.append(MutantResult(rule, rel, lineno, "survived",
                                                    "테스트가 이 결함을 잡지 못했다"))
                        continue
                    if not _typechecks(project_root):
                        results.append(MutantResult(rule, rel, lineno, "invalid",
                                                    "타입/구문 검사 실패 — 폐기"))
                        continue
                    results.append(MutantResult(rule, rel, lineno, "killed"))
                finally:
                    target.write_text(original, encoding="utf-8")
        finally:
            # 어떤 경로로 끝나도 원본을 되돌린다
            target.write_text(original, encoding="utf-8")
            shutil.rmtree(backup, ignore_errors=True)

    # ── 컬렉션 멤버 제거 (TS-022) ───────────────────────────────────────────
    #
    # 줄 변이가 도달하지 못하는 결함 모양이다. `routes.ts` 는 증거가 6줄 실행하는데
    # 비교·논리·조건이 없어 변이 지점이 0곳이었다. 그래서 "명세가 보호를 요구하는
    # 경로가 목록에서 사라진다"(= TS-013) 를 주입할 수 없었다.
    all_sources = [e.split(" (")[0] for e in cov["sources"]]
    spec = spec_text(project_root, feature_id)
    coll_cands = collection_candidates(project_root, all_sources)
    site_total += len(coll_cands)
    for coll_name, declared_in, member in select_spread(coll_cands, budget_coll):
        found = [p for p in root.rglob(Path(declared_in).name)
                 if "node_modules" not in p.parts]
        if not found:
            continue
        target = found[0]
        original = target.read_text(encoding="utf-8")
        mutated = drop_member(original, coll_name, member)
        if mutated is None or mutated == original:
            continue
        rule = f"컬렉션 멤버 제거 ({coll_name} ← {member!r})"
        rel = str(target.relative_to(root)).replace("\\", "/")
        lineno = _member_line(original, coll_name, member)
        try:
            target.write_text(mutated, encoding="utf-8")
            failed = _tests_fail(project_root, feature_id, test_files)
            if not failed:
                # 명세가 이 멤버를 지목하는가 — 생존의 의미가 갈린다 (TS-023)
                if spec_names(member, spec):
                    results.append(MutantResult(
                        rule, rel, lineno, "survived",
                        f"{member!r} 를 목록에서 지웠는데 테스트가 전부 통과했다. "
                        f"**명세가 이 경로를 지목한다** — 증거의 진짜 공백이다 "
                        f"(목록을 순회하는 테스트는 멤버가 사라지면 덜 돌 뿐이다)",
                    ))
                else:
                    results.append(MutantResult(
                        rule, rel, lineno, "out-of-spec",
                        f"{member!r} 를 지웠는데 통과했다. 다만 **명세가 이 멤버를 "
                        f"요구하지 않는다** — 테스트의 공백이 아니라 명세의 공백이다. "
                        f"고정하려면 먼저 명세에 적어야 한다 (TS-014)",
                    ))
            elif not _typechecks(project_root):
                # **폐기가 아니라 '타입이 잡음'이다** (TS-022).
                #
                # `drop_member` 는 배열 리터럴을 유지하므로 구문은 **구성상 유효하다.**
                # 그런데도 tsc 가 실패했다면 그것은 구문 파괴가 아니라 **타입 수준의
                # 결함 감지**다 — `Record<ProtectedPath, …>` 처럼 목록과 소비처가
                # 타입으로 묶여 있으면 멤버를 지우는 순간 컴파일이 막힌다.
                #
                # 증거 점수의 분자에는 넣지 않는다. 잡은 것은 테스트가 아니라
                # 컴파일러이고, 게이트가 묻는 것은 **증거의 품질**이다.
                # 그래도 '폐기'로 묻어버리면 **구조적 보호가 있다는 사실**이 사라진다.
                results.append(MutantResult(
                    rule, rel, lineno, "types",
                    f"테스트가 아니라 **타입 검사**가 잡았다 — {coll_name} 이 "
                    f"소비처와 타입으로 묶여 있어 멤버를 지우면 컴파일이 막힌다",
                ))
            else:
                results.append(MutantResult(rule, rel, lineno, "killed"))
        finally:
            target.write_text(original, encoding="utf-8")

    killed = sum(1 for r in results if r.status == "killed")
    survived = sum(1 for r in results if r.status == "survived")
    invalid = sum(1 for r in results if r.status == "invalid")
    # 타입 검사가 잡은 것 — 증거 점수의 분자에 넣지 않는다 (잡은 것은 테스트가 아니다).
    # 그래도 **구조적 보호가 있다는 사실**은 따로 센다 (TS-022).
    by_types = sum(1 for r in results if r.status == "types")
    # 명세가 요구하지 않는 멤버의 생존 — 증거의 공백이 아니므로 분모에서 제외한다 (TS-023).
    # 테스트로 고정하려면 먼저 명세에 적어야 하고, 적지 않은 채 고정하면 TS-014 다.
    out_of_spec = sum(1 for r in results if r.status == "out-of-spec")
    scored = killed + survived
    return {
        "feature": feature_id,
        "sources": cov["sources"][:max_files],
        "mutants": results,
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "types": by_types,
        "out_of_spec": out_of_spec,
        "score": round(killed / scored, 4) if scored else None,
        # 후보 총수와 실제 시도 수 — 예산 때문에 몇 개를 건너뛰었는지 보이게 한다.
        # 이것이 없으면 "점수 40%" 가 몇 개 표본에 근거한 수치인지 알 수 없다 (TS-022).
        "sites": site_total,
        "attempted": len(results),
        # 미실행이라 제외한 후보 수 (TS-026). 0 이 아니면 **이전 구현이 그만큼의
        # 생존 보장 변이를 점수에 넣고 있었다**는 뜻이다.
        "skipped_unexecuted": skipped_unexecuted,
        # 증거가 닿는 변이 지점 줄 수. `skipped_unexecuted` 와 **같은 단위**다 —
        # 도달률의 분자/분모가 되므로 변이 수(`attempted`)와 섞으면 안 된다.
        "reached_lines": reached_lines,
        # 줄 지도를 못 얻은 파일 — 그 파일은 미실행 줄 필터 없이 변이됐다.
        # 비어 있지 않으면 점수를 **과소평가일 수 있다**고 읽어야 한다.
        "unmapped_files": unmapped,
    }


def format_mutation(report: dict[str, Any]) -> str:
    """돌연변이 측정 결과를 사람이 읽을 표로."""
    bar = "=" * 68
    if "error" in report:
        return f"[오류] {report['error']}"

    lines = [
        bar,
        f"돌연변이 측정 — {report['feature']} 의 증거가 실제로 무는가",
        bar,
        f"  변이 대상: {', '.join(report['sources'])}",
        "",
        f"  잡음(killed) {report['killed']} / 생존(survived) {report['survived']}"
        f" / 폐기(invalid) {report['invalid']}"
        + (f" / 타입이 잡음(types) {report['types']}" if report.get("types") else "")
        + (f" / 명세 범위 밖 {report['out_of_spec']}" if report.get("out_of_spec") else ""),
    ]
    # 표본 크기를 함께 출력한다 — 점수만 보면 몇 개에 근거한 수치인지 알 수 없다
    sites, attempted = report.get("sites"), report.get("attempted")
    if sites is not None and attempted is not None:
        skipped = sites - attempted
        lines.append(
            f"  표본: 후보 {sites}곳 중 {attempted}곳 시도"
            + (f" — 예산으로 {skipped}곳 건너뜀 (--max-per-file 로 늘릴 수 있다)"
               if skipped > 0 else " (전수)")
        )
    # 미실행 줄을 제외했다는 사실을 적는다 (TS-026). 이것을 적지 않으면 "후보 3곳"이
    # 왜 적은지 알 수 없고, 적은 후보를 '테스트가 약하다'로 오독하게 된다.
    skipped_unexec = report.get("skipped_unexecuted")
    if skipped_unexec:
        lines.append(
            f"  제외: 미실행 줄 {skipped_unexec}곳 — 증거가 지나가지 않는 자리다. "
            "넣으면 생존이 보장되므로 점수에 넣지 않는다 (TS-026)"
        )
    unmapped = report.get("unmapped_files")
    if unmapped:
        lines.append(
            f"  ⚠ 줄 지도를 얻지 못한 파일 {len(unmapped)}개: {', '.join(unmapped[:3])}"
            " — 이 파일은 미실행 줄 필터 없이 변이됐다. 점수가 **과소평가일 수 있다**"
        )

    if report["score"] is not None:
        lines.append(f"  돌연변이 점수: {report['score'] * 100:.0f}%  (잡음 / (잡음+생존))")
        # **점수와 도달률을 함께** 적는다 (TS-026). 점수만 보면 "100%" 가 '테스트가
        # 완벽하다'로 읽히지만, 그것은 **증거가 지나가는 자리에서만** 참이다.
        # 미실행 줄을 분모에서 뺀 대가로 점수가 올라가므로, 무엇을 뺐는지 같은 줄에
        # 적지 않으면 TS-024 의 '발표된 수치가 실제보다 좋아 보이는' 모양이 된다.
        reached = report.get("reached_lines") or 0
        reach_total = reached + (skipped_unexec or 0)
        if skipped_unexec and reach_total:
            lines.append(
                f"  도달률: 변이 가능 지점 {reach_total}줄 중 {reached}줄에 증거가 닿는다"
                f" ({reached / reach_total * 100:.0f}%)"
                " — 점수는 **닿는 자리에서만** 측정한 값이다"
            )
    else:
        lines.append("  점수 없음 — 유효한 변이를 만들지 못했다")

    lines += ["", "  변이별 결과", "  " + "-" * 64]
    marks = {"killed": "잡음  ", "survived": "생존  ", "invalid": "폐기  ",
             "types": "타입잡음", "out-of-spec": "명세밖 "}
    for r in report["mutants"]:
        lines.append(f"  {marks.get(r.status, r.status)} {r.file}:{r.line}  {r.rule}")
        if r.detail:
            lines.append(f"           {r.detail}")

    if report["survived"]:
        primary = report["sources"][0].split(" (")[0] if report["sources"] else ""
        own = [r for r in report["mutants"]
               if r.status == "survived" and r.file.endswith(primary)]
        other = [r for r in report["mutants"]
                 if r.status == "survived" and not r.file.endswith(primary)]
        lines += [
            "",
            f"  ⚠ 생존 {report['survived']}건 — 구현을 바꿨는데 테스트가 통과했다.",
        ]
        if own:
            lines.append(
                f"    그중 {len(own)}건은 **이 기능이 소유한 파일**({primary})에 있다 —"
            )
            lines.append("    증거의 진짜 구멍이다. 단정을 추가할 가치가 있다.")
        if other:
            files = sorted({r.file.rsplit('/', 1)[-1] for r in other})
            lines.append(
                f"    {len(other)}건은 **다른 파일**({', '.join(files)})에 있다 —"
            )
            # 이전 문구는 "스쳐 지나간 파일 / 부수적 실행일 뿐 이 기능의 책임이
            # 아닐 수 있다 / 해당 파일을 소유한 기능의 측정에서 확인하라"였다.
            # **틀린 조언이다 (TS-026).** 변이 후보를 실행된 줄로 거른 뒤로는
            # 생존 변이가 놓인 줄은 **이 기능의 증거가 실제로 지나간 줄**이다.
            # 다른 기능의 측정으로 넘기면 그 기능의 테스트는 그 줄에 닿지 않을 수
            # 있고, 그러면 아무도 확인하지 않은 채 양쪽에서 책임이 사라진다.
            # 실제로 TS-023 이 F-005 의 생존 3건을 이 논리로 F-001~003 에 넘겼고,
            # 그 3건의 실제 원인은 소유권이 아니라 **미실행**이었다.
            lines.append(
                "    그 줄도 **이 기능의 증거가 실제로 실행한다**(미실행 줄은 제외됐다)."
            )
            lines.append(
                "    즉 소유권은 '단정을 어디에 쓸지'를 말할 뿐, 필요 여부를 말하지 않는다 —"
            )
            lines.append(
                "    다른 기능의 측정으로 넘기면 그 테스트는 이 줄에 닿지 않을 수 있다."
            )
        lines += [
            "",
            "  해석 주의: 점수는 '증거가 닿는 자리에서 몇 %를 잡았나'이지 "
            "'이 기능의 테스트 품질'이 아니다.",
            "  변이 대상 파일은 커버리지로 고르므로 다른 기능이 소유한 파일이 섞인다.",
        ]

    # 명세 범위 밖 생존은 **다른 종류의 신호**다 — 테스트를 고치라는 뜻이 아니다 (TS-023)
    if report.get("out_of_spec"):
        oos = [r for r in report["mutants"] if r.status == "out-of-spec"]
        lines += [
            "",
            f"  ◆ 명세 범위 밖 {len(oos)}건 — 지워도 통과하지만 **명세가 요구하지 않는다.**",
            "    테스트의 공백이 아니라 **명세의 공백**이다. 앱이 명세를 넘어 구현했다.",
            "    여기에 단정을 추가하면 '명세에 없는 것을 단정하는 테스트'가 되고,",
            "    그것은 TS-014 가 '측정 도구 오류'로 분류해 고쳤던 바로 그 패턴이다.",
            "    고정이 필요하다고 판단되면 **먼저 명세에 적는다.**",
        ]
        for r in oos:
            lines.append(f"      · {r.rule}")

    if report.get("types"):
        lines += [
            "",
            f"  ◆ 타입이 잡음 {report['types']}건 — 테스트가 아니라 컴파일러가 막았다.",
            "    증거 점수의 분자에는 넣지 않았다(잡은 것이 테스트가 아니므로).",
            "    다만 **구조적 보호가 존재한다**는 사실이므로 '폐기'로 묻지 않는다.",
        ]
    lines.append(bar)
    return "\n".join(lines)

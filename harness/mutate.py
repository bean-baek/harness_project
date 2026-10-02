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


def _candidate_lines(text: str, pattern: str) -> list[int]:
    """해당 규칙이 적용 가능한 줄 번호. 주석·import 줄은 제외한다."""
    hits = []
    for i, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*", "import ", "export type")):
            continue
        if re.search(pattern, line):
            hits.append(i)
    return hits


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
) -> dict[str, Any]:
    """기능 하나의 증거에 대해 돌연변이 점수를 측정한다.

    Returns:
        {feature, mutants: [...], killed, survived, invalid, score, sources}
        score = killed / (killed + survived) — invalid 는 분모에서 제외한다.
    """
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

    results: list[MutantResult] = []
    for target in targets:
        original = target.read_text(encoding="utf-8")
        rel = str(target.relative_to(root)).replace("\\", "/")
        applied = 0
        backup = tempfile.mkdtemp(prefix="harness-mut-")
        backup_file = Path(backup) / target.name
        backup_file.write_text(original, encoding="utf-8")
        try:
            for rule, pattern, replacement in MUTATIONS:
                if applied >= MAX_MUTANTS_PER_FILE:
                    break
                lines = _candidate_lines(original, pattern)
                if not lines:
                    continue
                lineno = lines[0]
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

    killed = sum(1 for r in results if r.status == "killed")
    survived = sum(1 for r in results if r.status == "survived")
    invalid = sum(1 for r in results if r.status == "invalid")
    scored = killed + survived
    return {
        "feature": feature_id,
        "sources": cov["sources"][:max_files],
        "mutants": results,
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "score": round(killed / scored, 4) if scored else None,
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
        f" / 폐기(invalid) {report['invalid']}",
    ]
    if report["score"] is not None:
        lines.append(f"  돌연변이 점수: {report['score'] * 100:.0f}%  (잡음 / (잡음+생존))")
    else:
        lines.append("  점수 없음 — 유효한 변이를 만들지 못했다")

    lines += ["", "  변이별 결과", "  " + "-" * 64]
    marks = {"killed": "잡음  ", "survived": "생존  ", "invalid": "폐기  "}
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
                f"    {len(other)}건은 **스쳐 지나간 파일**({', '.join(files)})에 있다 —"
            )
            lines.append(
                "    커버리지가 잡은 부수적 실행일 뿐 이 기능의 책임이 아닐 수 있다."
            )
            lines.append(
                "    해당 파일을 소유한 기능의 측정에서 다시 확인하는 것이 맞다."
            )
        lines += [
            "",
            "  해석 주의: 점수는 '변이 대상 파일에서 몇 %를 잡았나'이지 "
            "'이 기능의 테스트 품질'이 아니다.",
            "  변이 대상은 커버리지로 고르므로 다른 기능이 소유한 파일이 섞인다.",
        ]
    lines.append(bar)
    return "\n".join(lines)

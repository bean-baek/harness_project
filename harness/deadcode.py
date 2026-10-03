"""
harness/deadcode.py
───────────────────
**하네스가 자기 자신을 감사한다 — 고아 코드와 죽은 설정.**

왜 필요한가 (TS-019):
  죽은 설정이 **두 번** 나왔다.
    TS-007 — `HARNESS_PERSISTENT` / `DATABASE_URL` 이 그래프 빌더에 전달되지 않아
             설정을 켜도 항상 `InMemorySaver` 였다.
    TS-019 — `HARNESS_EVAL_THRESHOLD` 가 어디서도 읽히지 않았다. 라우터는 `75` 를
             하드코딩했고 README 는 그 환경변수를 "Evaluator 합격선"으로 광고했다.
             `DEV_PORT`/`API_PORT` 도 같았다.

  두 번 나온 패턴은 사람이 기억으로 막을 수 없다. 기계가 센다.

  같은 감사에서 고아 코드 21건도 나왔다 — 호출되지 않는 함수 6개, 바인딩되지 않는
  도구 목록 2개, 구현된 적 없는 기능의 프롬프트 4개, 리팩터 후 남은 상수 9개.

오탐 방어 (TS-017 의 교훈 — 오탐을 내는 검사는 없는 검사보다 나쁘다):
  - 참조는 `Name`·`Attribute`·`alias`·**문자열 리터럴**에서 모두 수집한다.
    문자열까지 보는 이유: LangGraph 노드는 `add_node("done", fn)` 으로 등록되고
    `getattr(mod, "name")` 패턴도 있다.
  - **정의 줄 자신의 참조는 세지 않는다.** 이것을 빠뜨린 첫 구현에서 CLI 명령 11개와
    그래프 노드 3개가 '미사용'으로 나왔다 (`set_defaults(func=cmd_next)` 는
    같은 파일 안의 참조다).
  - 프레임워크 규약(`main`, 던더)과 `from __future__ import annotations` 는 면제한다.
    후자는 컴파일러 지시자이므로 이름으로는 영원히 '미사용'이다.

한계:
  정적 분석이다. `eval`/`importlib` 동적 참조는 보지 못한다. 그래서 결과는
  **보고**이고, 게이트로 쓸지는 호출자가 정한다 (`verification/repro_ts019.py` 는 게이트로 쓴다 —
  이 레포에 동적 참조가 없다는 것을 확인했기 때문이다).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

#: 감사에서 제외하는 디렉터리
SKIP_DIRS = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".git", "dist", "build",
    "web_target", ".harness_memory", ".pytest_cache", ".mypy_cache",
    # 검증 픽스처는 **의도적으로 작은 가짜 프로젝트**다 (TS-025). 그 안의 함수는
    # 하네스가 호출하지 않으므로 고아로 보이지만 고아가 아니다 — 픽스처의 역할이
    # "외부 프로젝트처럼 보이는 것"이기 때문이다. 감사 범위에서 뺀다.
    "fixtures",
})

# 이 집합을 `project.SKIP_DIRS` 와 합치지 말 것 — 둘은 **반대 방향**이다.
#   `deadcode.SKIP_DIRS`  하네스 자기 감사의 범위. 픽스처는 하네스 코드가 아니므로 뺀다.
#   `project.SKIP_DIRS`   검사 **대상** 프로젝트 안에서 무시할 디렉터리 (빌드 산출물 등).
# `inspect` 는 후자를 쓰고 **픽스처 안에서 동작해야 한다** — 거기에 "fixtures" 를 넣으면
# 픽스처를 대상으로 지정했을 때 파일을 하나도 못 찾는다. `repro_ts025.py` [10] 이 그것을 고정한다.

#: 참조가 없어도 정상인 이름 — 프레임워크가 호출하거나 컴파일러 지시자다
EXEMPT_NAMES = frozenset({
    "main", "__init__", "__main__", "__dir__", "__getattr__", "__repr__",
    "__str__", "__call__", "__enter__", "__exit__", "__post_init__",
    "annotations",          # from __future__ import — 이름으로는 영원히 미사용
})


@dataclass
class Finding:
    kind: str          # 'orphan' | 'unused-import' | 'dead-config'
    name: str
    file: str
    line: int
    detail: str = ""

    def line_text(self) -> str:
        head = f"  {self.file}:{self.line}  {self.name}"
        return f"{head}\n         └ {self.detail}" if self.detail else head


def python_files(root: Path) -> list[Path]:
    """감사 대상 `.py`. **`.venv` 안으로 내려가지 않는다** (TS-030).

    `rglob("*.py")` 는 `.venv` 안의 수만 개 파일을 전부 걷고 나서 걸렀다 —
    `deadcode.audit` 이 5.6초였다. 결과는 같고 비용만 줄인다.
    """
    from harness.project import walk_files

    return sorted(walk_files(root, SKIP_DIRS, (".py",)))


def _collect(root: Path):
    """(정의, 참조) 를 모은다.

    정의: (name, kind) -> [(file, line)]
    참조: name -> {(file, line)}   — 정의 줄에서의 Store 는 제외
    """
    definitions: dict[tuple[str, str], list[tuple[str, int]]] = {}
    references: dict[str, set[tuple[str, int]]] = {}

    for p in python_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue

        def_lines: set[int] = set()
        for node in tree.body:                       # 최상위만 — 메서드는 제외
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault((node.name, "def"), []).append((rel, node.lineno))
                def_lines.add(node.lineno)
            elif isinstance(node, ast.ClassDef):
                definitions.setdefault((node.name, "class"), []).append((rel, node.lineno))
                def_lines.add(node.lineno)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        definitions.setdefault((t.id, "const"), []).append((rel, node.lineno))
                        def_lines.add(node.lineno)

        for node in ast.walk(tree):
            line = getattr(node, "lineno", -1)
            if isinstance(node, ast.Name):
                if line in def_lines and isinstance(node.ctx, ast.Store):
                    continue            # 정의 그 자체 — 참조가 아니다
                references.setdefault(node.id, set()).add((rel, line))
            elif isinstance(node, ast.Attribute):
                references.setdefault(node.attr, set()).add((rel, line))
            elif isinstance(node, ast.alias):
                nm = node.asname or node.name.split(".")[-1]
                references.setdefault(nm, set()).add((rel, line))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 노드 등록·getattr 처럼 이름이 문자열로 쓰이는 경우
                for tok in node.value.replace("(", " ").replace(")", " ").split():
                    references.setdefault(tok.strip(".,:;'\"`!?"), set()).add((rel, line))
    return definitions, references


def find_orphans(root: str | Path) -> list[Finding]:
    """정의됐지만 **정의 외 참조가 0건**인 최상위 심볼."""
    root = Path(root).resolve()
    definitions, references = _collect(root)
    out: list[Finding] = []
    for (name, kind), places in sorted(definitions.items()):
        if name in EXEMPT_NAMES or name.startswith("test_"):
            continue
        refs = references.get(name, set()) - set(places)
        if refs:
            continue
        for rel, line in places:
            out.append(Finding("orphan", f"{kind} {name}", rel, line,
                               "정의 외 참조 0건"))
    return out


def find_unused_imports(root: str | Path) -> list[Finding]:
    """임포트했지만 그 파일 안에서 쓰지 않는 이름."""
    root = Path(root).resolve()
    out: list[Finding] = []
    for p in python_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        imported: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    imported[a.asname or a.name.split(".")[0]] = node.lineno

        lines = src.split("\n")
        for name, line in sorted(imported.items(), key=lambda kv: kv[1]):
            if name in EXEMPT_NAMES or name == "*" or name.startswith("_"):
                continue
            # 임포트 줄을 제외한 소스에 이름이 등장하는가 (주석·문자열 포함, 보수적)
            body = "\n".join(l for i, l in enumerate(lines, 1) if i != line)
            if re.search(rf"\b{re.escape(name)}\b", body):
                continue
            out.append(Finding("unused-import", name, rel, line, "이 파일에서 사용 0건"))
    return out


def find_dead_config(root: str | Path,
                     config_file: str = "config.py",
                     docs: tuple[str, ...] = ("README.md", "README_EN.md")
                     ) -> list[Finding]:
    """**문서가 광고하는데 코드가 읽지 않는 설정** — TS-007/TS-019 의 양식.

    두 가지를 함께 본다:
      1. `config.py` 의 상수가 다른 곳에서 참조되는가
      2. 그 상수가 환경변수를 읽는다면, 그 환경변수가 문서에 등장하는가

    둘 다 맞으면 **문서는 광고하지만 바꿔도 아무 일이 없는 설정**이다.
    상수가 죽었지만 문서에도 없으면 단순 고아이므로 `find_orphans` 가 잡는다.
    """
    root = Path(root).resolve()
    cfg_path = root / config_file
    if not cfg_path.is_file():
        return []
    src = cfg_path.read_text(encoding="utf-8")

    documented = set()
    for doc in docs:
        dp = root / doc
        if dp.is_file():
            documented |= set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`",
                                         dp.read_text(encoding="utf-8")))

    _, references = _collect(root)
    out: list[Finding] = []
    for m in re.finditer(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", src, re.M):
        name, rhs = m.group(1), m.group(2)
        line = src[:m.start()].count("\n") + 1
        envm = re.search(r'environ\.get\(\s*["\']([A-Za-z_]+)["\']', rhs)
        if not envm:
            continue
        env = envm.group(1)
        refs = {f for f, _ in references.get(name, set()) if f != config_file}
        if refs:
            continue
        if env in documented:
            out.append(Finding(
                "dead-config", env, config_file, line,
                f"{name} 을 어디서도 읽지 않습니다 — 문서는 광고하지만 바꿔도 "
                f"아무 일이 없습니다 (TS-007/TS-019 의 양식)",
            ))
    return out


def audit(root: str | Path) -> list[Finding]:
    """세 검사를 한 번에."""
    return (find_dead_config(root) + find_orphans(root) + find_unused_imports(root))


def format_audit(findings: list[Finding], root: str | Path) -> str:
    bar = "=" * 72
    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    titles = {
        "dead-config":   "죽은 설정 — 문서가 광고하지만 코드가 읽지 않는다",
        "orphan":        "고아 코드 — 정의됐지만 참조가 0건",
        "unused-import": "미사용 임포트",
    }
    lines = [bar, f"하네스 자기 감사 — {Path(root).resolve()}", bar]
    for kind in ("dead-config", "orphan", "unused-import"):
        items = by_kind.get(kind, [])
        lines += ["", f"  [{titles[kind]}]  {len(items)}건", "  " + "-" * 68]
        if not items:
            lines.append("    없음")
        for f in items:
            lines.append(f.line_text())
    lines += [
        "",
        "  " + "-" * 68,
        "  주의: 정적 분석이므로 eval·importlib 동적 참조는 보지 못한다.",
        "  삭제 전에 한 번 눈으로 확인할 것.",
        bar,
    ]
    return "\n".join(lines)


if __name__ == "__main__":                              # pragma: no cover
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    results = audit(target)
    print(format_audit(results, target))
    sys.exit(1 if results else 0)

"""
harness/inspect.py
──────────────────
**프로젝트 검수 — 사람의 의도 없이 객관적으로 판정되는 것을 찾아낸다.**

이 모듈이 존재하는 이유:
  명세(`features.json`)는 **의도**이고 의도는 사람만 안다. 그런데 "사람이 전부
  적어야 한다"는 것도 틀렸다. 검사할 수 있는 것 중 상당 부분은 의도를 몰라도
  판정된다 — **코드 안의 서로 다른 두 지점이 어긋나는가**가 그것이다.

순환과 불변식의 구분 (이 프로젝트의 가장 큰 함정, TS-013):
  순환   — 구현 A 를 읽어 명세를 쓰고 구현 A 를 검사한다. 항상 통과한다. 무의미.
  불변식 — 선언 D 와 구현 I 의 **일치**를 검사한다. 둘 중 하나가 틀리면 잡힌다.

  예: `routes.ts` 에 `PROTECTED_PATHS = ['/', '/dashboard', '/profile', '/settings']`
  가 있고 `App.tsx` 가 라우트를 등록한다. "선언된 4개가 모두 등록되었는가"는
  코드에서 추출했지만 순환이 아니다 — 누가 경로를 추가하고 등록을 빼먹으면 잡힌다.
  판정에 "무엇이 보호되어야 하는가"라는 의도가 **필요하지 않다.**

따라서 보고는 두 갈래다:
  `auto=True`  — 지금 바로 판정했다. 결과가 ok 또는 violated.
  `auto=False` — 의도가 필요하다. 후보로만 제시하고 사람의 승인을 요구한다.

명세 초안을 별도 파일에 쓰는 이유:
  검수가 뽑은 항목을 `features.json` 에 바로 넣으면, 하네스가 **자기가 코드에서
  뽑은 명세로 그 코드를 검사**하게 된다 — 정확히 순환이다. 그래서 초안은
  `features.draft.json` 에 쓰고, 사람이 읽고 옮겨야 효력이 생긴다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness import project
from harness.project import SKIP_DIRS, ProjectConfig

#: 소스로 볼 확장자
SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".py")

#: 경로 문자열 배열 선언 — `const X = ['/a', '/b']`
_PATH_ARRAY_RE = re.compile(
    r"(?:const|let|var)\s+([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*\[([^\]]*)\]"
)
#: 배열 안의 경로 리터럴
_PATH_LITERAL_RE = re.compile(r"""['"](/[A-Za-z0-9_\-/:*.]*)['"]""")
#: 라우터 등록 — `path="/a"` / `path: '/a'` (리터럴만)
_ROUTE_PROP_RE = re.compile(r"""path\s*[=:]\s*\{?\s*['"](/[A-Za-z0-9_\-/:*.]*)['"]""")
#: 변수로 등록 — `path={path}` / `path={x.slice(1)}`. 리터럴이 아니면 정적으로 못 본다.
_NONLITERAL_ROUTE_RE = re.compile(r"""path\s*=\s*\{\s*(?!['"])[A-Za-z_$]""")
#: export 심볼
_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
#: import 문에서 가져오는 이름들
_IMPORT_NAMES_RE = re.compile(r"import\s+(?:type\s+)?\{([^}]*)\}\s*from")
_IMPORT_DEFAULT_RE = re.compile(r"import\s+(?:type\s+)?([A-Za-z_$][\w$]*)\s*(?:,|from)")
#: 폼·제출
_FORM_RE = re.compile(r"<form\b|onSubmit\s*[=:]")
#: 에러 경로
_AWAIT_RE = re.compile(r"\bawait\b")
_CATCH_RE = re.compile(r"\bcatch\s*[({]|\.catch\s*\(|except\b")


@dataclass
class Check:
    """검수 항목 한 건."""

    kind: str
    claim: str
    #: 선언 지점 — 사람이 쓴 '무엇이 있어야 하는가'
    declared_at: str = ""
    #: 구현 지점 — '실제로 그렇게 되어 있는가'
    implemented_at: str = ""
    #: 'ok' | 'violated' | 'advisory' | 'needs-intent'
    #:
    #: `advisory` 가 왜 필요한가 (TS-029): `violated` 는 **차단 근거가 서는** 판정이다.
    #: 그런데 검사기에 **알려진 맹점**이 있으면 그 판정으로 차단할 수 없다 —
    #: 재export·동적 import·전이 import 를 못 보는 검사가 그렇다. 실측에서
    #: `untested-source` 가 14건을 보고했고 그중 2건이 오탐이었다.
    #:
    #: 이전에는 그 둘도 `violated` 였고, 그래서 CI 가 `cli inspect || true` 로
    #: **종료 코드를 버리고** 있었다. 오탐이 있는 판정 하나 때문에 정확한 판정
    #: (죽은 npm 스크립트, 라우트 누락)까지 차단력을 잃었다. 둘을 나눈다.
    verdict: str = "needs-intent"
    detail: str = ""
    #: 의도 없이 판정 가능한가
    auto: bool = False

    def line(self) -> str:
        mark = {"ok": "통과", "violated": "위반", "advisory": "권고",
                "needs-intent": "의도필요"}
        head = f"  [{mark.get(self.verdict, self.verdict)}] {self.claim}"
        parts = [head]
        if self.declared_at and self.implemented_at:
            parts.append(f"         선언 {self.declared_at}  ↔  구현 {self.implemented_at}")
        elif self.declared_at:
            parts.append(f"         위치 {self.declared_at}")
        if self.detail:
            parts.append(f"         └ {self.detail}")
        return "\n".join(parts)


@dataclass
class Readiness:
    """하네스를 이 프로젝트에 붙일 수 있는가 — 막는 것이 무엇인가."""

    runner: str = ""
    runner_runnable: bool = False
    runner_note: str = ""
    test_files: int = 0
    spec_exists: bool = False
    spec_features: int = 0
    spec_ids_matching: int = 0
    tagged_features: int = 0
    blockers: list[str] = field(default_factory=list)

    def attachable(self) -> bool:
        return not self.blockers


@dataclass
class Report:
    cfg: ProjectConfig
    findings: list[project.Finding] = field(default_factory=list)
    readiness: Readiness = field(default_factory=Readiness)
    checks: list[Check] = field(default_factory=list)
    draft: list[dict[str, Any]] = field(default_factory=list)
    #: 명세가 필요하지만 내용이 구현에만 있는 자리 — 초안이 아니라 질문이다 (TS-028)
    questions: list[Any] = field(default_factory=list)


# ── 파일 수집 ────────────────────────────────────────────────────────────────

def _source_files(root: Path, cfg: ProjectConfig) -> list[Path]:
    """선언된 소스 디렉터리 안의 소스 파일 (테스트 제외)."""
    out: list[Path] = []
    for d in cfg.source_dirs:
        base = (root / d).resolve()
        if not base.is_dir():
            continue
        for p in project.walk_files(base, SKIP_DIRS, SOURCE_EXTS):
            if not cfg.is_test_file(p.name):
                out.append(p)
    return sorted(set(out))


def _test_files(root: Path, cfg: ProjectConfig) -> list[Path]:
    """테스트 파일 전부. **`node_modules` 안으로 내려가지 않는다** (TS-030).

    이전 구현은 `root.rglob("*")` 로 전부 걷고 나서 `SKIP_DIRS` 로 걸렀다.
    `web_target/node_modules` 항목이 17,721개여서 호출당 1.45초였고, inspect 안에서
    세 번 불려 4초가 넘었다. 결과는 같고 비용만 줄인다.
    """
    return sorted(
        p for p in project.walk_files(root, SKIP_DIRS) if cfg.is_test_file(p.name)
    )


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return p.name


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ── 자동 판정 검사 ───────────────────────────────────────────────────────────

def check_dead_scripts(root: Path) -> list[Check]:
    """package.json 의 스크립트가 **실제로 실행 가능한가.**

    근거 (TS-012): 이 레포의 npm 스크립트 3개가 죽어 있었다 — 참조하는 바이너리가
    의존성에 없었다. 아무도 몰랐던 이유는 아무도 실행해보지 않았기 때문이다.
    이것은 의도를 전혀 모르고도 판정된다: 선언(scripts)과 구현(dependencies)의 일치.
    """
    pkg_path = root / "package.json"
    if not pkg_path.is_file():
        return []
    try:
        pkg = json.loads(_read(pkg_path))
    except json.JSONDecodeError:
        return [Check("dead-script", "package.json 이 파싱되지 않습니다",
                      declared_at="package.json", verdict="violated", auto=True)]
    scripts = pkg.get("scripts") or {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    bin_dir = root / "node_modules" / ".bin"
    installed = {p.stem.lower() for p in bin_dir.iterdir()} if bin_dir.is_dir() else set()

    #: npm 이 자체 제공하거나 OS 가 제공하는 것 — 의존성에 없어도 정상
    builtin = {"npm", "node", "npx", "echo", "rm", "mkdir", "cp", "mv", "set",
               "cross-env", "yarn", "pnpm", "cd", "python", "python3", "pip"}

    checks: list[Check] = []
    for name, body in scripts.items():
        if not isinstance(body, str):
            continue
        # 스크립트가 부르는 첫 실행 파일들 (&&, | 로 나뉜 각 절의 선두)
        tools = []
        for segment in re.split(r"&&|\|\||;|\|", body):
            words = segment.strip().split()
            if not words:
                continue
            tool = words[0]
            if tool in ("npx", "pnpm", "yarn") and len(words) > 1:
                tool = next((w for w in words[1:] if not w.startswith("-")), tool)
            tools.append(tool)
        missing = [
            t for t in tools
            if t.lower() not in builtin
            and t.split("/")[-1] not in deps and t not in deps
            and t.lower() not in installed
            and not t.startswith((".", "/"))
        ]
        if missing:
            checks.append(Check(
                kind="dead-script",
                claim=f"npm script '{name}' 이 실행 가능하다",
                declared_at=f"package.json scripts.{name}",
                implemented_at="package.json dependencies",
                verdict="violated", auto=True,
                detail=f"{', '.join(missing)} 를 의존성·node_modules/.bin 에서 찾을 수 없습니다"
                       f" — 이 스크립트는 지금 실행되지 않습니다",
            ))
        else:
            checks.append(Check(
                kind="dead-script",
                claim=f"npm script '{name}' 이 실행 가능하다",
                declared_at=f"package.json scripts.{name}",
                implemented_at="package.json dependencies",
                verdict="ok", auto=True,
            ))
    return checks


def check_route_completeness(root: Path, cfg: ProjectConfig) -> list[Check]:
    """경로 **선언 목록**이 라우터에서 실제로 소비되는가.

    세 가지 경우를 구분한다. 구분을 틀리면 오탐이 나오고, **오탐을 내는 검사는
    없는 검사보다 나쁘다** (돌연변이 점수에서 같은 결론에 도달했다).

    1. 선언 목록을 **순회해서** 등록한다 (`PATHS.map(...)`)
       → 누락이 구조적으로 불가능하다. 통과. 비교할 것이 없다.
    2. 등록이 **전부 리터럴**이다 (`path="/a"`)
       → 선언 ⊆ 등록 을 비교할 수 있다. 빠진 것이 있으면 위반.
    3. 둘이 섞여 있다
       → 동적 등록 부분을 정적으로 볼 수 없다. **판정하지 않는다.**

    역방향(등록 ⊆ 선언)은 검사하지 않는다. 경로 목록은 보통 **부분집합**이다
    (`PROTECTED_PATHS` 에 `/login` 이 없는 것은 설계이지 누락이 아니다).
    근거 없는 방향을 검사하면 설계를 위반으로 보고한다 — 실측된 오탐이다.
    """
    declared: dict[str, tuple[str, str]] = {}   # path -> (const name, file)
    registered: dict[str, str] = {}             # path -> file
    dynamic_at: dict[str, str] = {}             # const name -> 순회 위치
    nonliteral_regs: list[str] = []             # path={변수} 가 있는 위치

    sources = _source_files(root, cfg)
    for p in sources:
        text = _read(p)
        rel = _rel(p, root)
        for m in _PATH_ARRAY_RE.finditer(text):
            const_name, body = m.group(1), m.group(2)
            paths = _PATH_LITERAL_RE.findall(body)
            if len(paths) < 2:          # 배열 하나에 경로 2개 이상일 때만 '목록 선언'으로 본다
                continue
            for path in paths:
                declared.setdefault(path, (const_name, rel))
        for m in _ROUTE_PROP_RE.finditer(text):
            registered.setdefault(m.group(1), rel)
        if _NONLITERAL_ROUTE_RE.search(text):
            nonliteral_regs.append(rel)

    if not declared:
        return []

    # 선언 목록을 순회하는 코드가 있는가 — 있으면 누락이 불가능하다
    for const_name in {v[0] for v in declared.values()}:
        iterate_re = re.compile(
            re.escape(const_name) + r"\s*\.\s*(?:map|forEach|flatMap)\s*\(|"
            r"(?:of|in)\s+" + re.escape(const_name) + r"\b"
        )
        for p in sources:
            if iterate_re.search(_read(p)):
                dynamic_at[const_name] = _rel(p, root)
                break

    checks: list[Check] = []
    by_const: dict[str, list[str]] = {}
    for path, (const_name, _) in declared.items():
        by_const.setdefault(const_name, []).append(path)

    for const_name, paths in sorted(by_const.items()):
        decl_file = next(f for _, (c, f) in declared.items() if c == const_name)
        if const_name in dynamic_at:
            checks.append(Check(
                kind="route-completeness",
                claim=f"{const_name} 의 모든 경로가 라우터에 등록된다",
                declared_at=decl_file,
                implemented_at=dynamic_at[const_name],
                verdict="ok", auto=True,
                detail=f"목록({len(paths)}개)을 순회해 등록하므로 누락이 구조적으로 "
                       f"불가능합니다 — 목록이 단일 출처입니다",
            ))
            continue
        if nonliteral_regs:
            checks.append(Check(
                kind="route-completeness",
                claim=f"{const_name} 의 모든 경로가 라우터에 등록된다",
                declared_at=decl_file,
                implemented_at=", ".join(sorted(set(nonliteral_regs))),
                verdict="needs-intent", auto=False,
                detail="등록에 변수 경로(path={...})가 섞여 있어 정적으로 판정할 수 "
                       "없습니다. 목록을 순회해 등록하도록 바꾸면 자동 판정됩니다",
            ))
            continue
        missing = sorted(set(paths) - set(registered))
        if missing:
            checks.append(Check(
                kind="route-completeness",
                claim=f"{const_name} 의 모든 경로가 라우터에 등록된다",
                declared_at=decl_file,
                implemented_at=", ".join(sorted(set(registered.values()))) or "(등록 없음)",
                verdict="violated", auto=True,
                detail=f"선언됐지만 등록되지 않은 경로: {', '.join(missing)}",
            ))
        else:
            checks.append(Check(
                kind="route-completeness",
                claim=f"{const_name} 의 모든 경로가 라우터에 등록된다",
                declared_at=decl_file,
                implemented_at=", ".join(sorted(set(registered.values()))),
                verdict="ok", auto=True,
                detail=f"선언 {len(paths)}개 전부 리터럴로 등록됨",
            ))
    return checks


#: `from './x'` / `require('./x')` 의 모듈 이름
_IMPORT_SPEC_RE = re.compile(
    r"""from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]""")


def _imported_stems(text: str) -> set[str]:
    """그 파일이 import 하는 모듈의 파일명(확장자 없이)."""
    out: set[str] = set()
    for m in _IMPORT_SPEC_RE.finditer(text):
        spec = m.group(1) or m.group(2) or ""
        if spec:
            out.add(Path(spec).stem)
    return out


def check_untested_sources(root: Path, cfg: ProjectConfig) -> list[Check]:
    """어떤 테스트 파일도 import 하지 않는 소스 파일.

    커버리지를 돌리지 않고 **정적으로** 판정한다 — 런너가 설치되지 않은 프로젝트에서도
    답이 나와야 한다. import 되지 않은 파일은 커버리지가 0 임이 확정이다.
    """
    # 타입 선언 파일(`.d.ts`)은 실행될 코드가 없다 — '커버리지 0' 이 당연하고
    # 결함이 아니다. 세면 오탐이 하나 늘어난다 (실측: `vite-env.d.ts`).
    sources = [p for p in _source_files(root, cfg) if not p.name.endswith(".d.ts")]
    if not sources:
        return []
    tests = _test_files(root, cfg)

    # **전이 import 를 따라간다.** 직접 import 만 보면 `App.tsx` 를 테스트가
    # import 하고 `App.tsx` 가 `Layout.tsx` 를 import 할 때 `Layout.tsx` 가
    # 실행되는데도 '미테스트'로 보고된다 — 실측에서 14건 중 2건이 그 오탐이었다.
    by_stem = {p.stem: p for p in sources}
    reached: set[str] = set()
    frontier: list[str] = []
    for t in tests:
        for stem in _imported_stems(_read(t)):
            if stem not in reached:
                reached.add(stem)
                frontier.append(stem)
    while frontier:
        cur = frontier.pop()
        src = by_stem.get(cur)
        if src is None:
            continue
        for dep in _imported_stems(_read(src)):
            if dep in by_stem and dep not in reached:
                reached.add(dep)
                frontier.append(dep)

    untested = [p for p in sources if p.stem not in reached]
    if not untested:
        return [Check(
            kind="untested-source",
            claim="모든 소스 파일이 최소 한 개의 테스트에서 import 된다",
            declared_at=", ".join(cfg.source_dirs),
            implemented_at=f"테스트 {len(tests)}개",
            verdict="ok", auto=True,
            detail=f"소스 {len(sources)}개 전부",
        )]
    shown = ", ".join(_rel(p, root) for p in untested[:8])
    if len(untested) > 8:
        shown += f" … 외 {len(untested) - 8}개"
    return [Check(
        kind="untested-source",
        claim="모든 소스 파일이 최소 한 개의 테스트에서 import 된다",
        declared_at=", ".join(cfg.source_dirs),
        implemented_at=f"테스트 {len(tests)}개",
        verdict="advisory", auto=True,
        detail=f"소스 {len(sources)}개 중 {len(untested)}개에 어떤 테스트도 (전이적으로도) "
               f"도달하지 않습니다: {shown}"
               "\n           (동적 import 는 이 검사가 보지 못합니다 — 그래서 권고입니다)",
    )]


def check_unreferenced_exports(root: Path, cfg: ProjectConfig) -> list[Check]:
    """export 됐지만 프로젝트 안에서 아무도 import 하지 않는 심볼 (죽은 코드)."""
    sources = _source_files(root, cfg)
    if not sources:
        return []
    exports: dict[str, str] = {}
    referenced: set[str] = set()
    for p in sources + _test_files(root, cfg):
        text = _read(p)
        rel = _rel(p, root)
        if p in sources:
            for m in _EXPORT_RE.finditer(text):
                exports.setdefault(m.group(1), rel)
        for m in _IMPORT_NAMES_RE.finditer(text):
            for raw in m.group(1).split(","):
                token = raw.strip().split(" as ")[0].strip()
                # `import { PROTECTED_PATHS, type ProtectedPath }` — 인라인 type 한정자를
                # 떼지 않으면 'type ProtectedPath' 라는 이름으로 등록되어, 실제로 쓰이는
                # 타입이 '미참조'로 보고된다 (실측된 오탐).
                if token.startswith("type "):
                    token = token[5:].strip()
                if token:
                    referenced.add(token)
        for m in _IMPORT_DEFAULT_RE.finditer(text):
            referenced.add(m.group(1))

    #: 프레임워크가 호출하는 진입점은 참조 없이도 정상이다
    entry = {"App", "default", "main", "Root", "Layout", "handler", "loader", "action",
             "metadata", "generateMetadata", "middleware"}
    orphans = sorted(
        n for n, f in exports.items()
        if n not in referenced and n not in entry and not f.endswith(("index.ts", "index.tsx"))
    )
    if not orphans:
        return [Check(
            kind="unreferenced-export",
            claim="export 된 모든 심볼이 어딘가에서 참조된다",
            declared_at=", ".join(cfg.source_dirs),
            implemented_at="프로젝트 전체 import",
            verdict="ok", auto=True, detail=f"export {len(exports)}개 전부",
        )]
    shown = ", ".join(f"{n} ({exports[n]})" for n in orphans[:6])
    if len(orphans) > 6:
        shown += f" … 외 {len(orphans) - 6}개"
    return [Check(
        kind="unreferenced-export",
        claim="export 된 모든 심볼이 어딘가에서 참조된다",
        declared_at=", ".join(cfg.source_dirs),
        implemented_at="프로젝트 전체 import",
        # 재export·동적 import 를 못 보는 것이 **선언된 맹점**이므로 차단하지 않는다
        # (TS-029). 맹점이 있는 판정으로 차단하면 오탐이 CI 를 영구히 빨간불로 만들고,
        # 그 압력이 `|| true` 를 낳아 **정확한 판정의 차단력까지** 함께 잃는다.
        verdict="advisory", auto=True,
        detail=f"export {len(exports)}개 중 {len(orphans)}개가 참조되지 않습니다: {shown}"
               f"\n           (재export·동적 import 는 이 검사가 보지 못합니다 — 그래서 권고입니다)",
    )]


# ── 의도가 필요한 후보 ───────────────────────────────────────────────────────

def candidates_needing_intent(root: Path, cfg: ProjectConfig) -> list[Check]:
    """자동 판정이 불가능한 지점. **후보로만** 제시한다.

    왜 자동 판정이 안 되는가: "이 폼이 무엇을 거부해야 하는가", "실패했을 때 무엇을
    보여야 하는가" 는 코드 어디에도 선언되어 있지 않다. 코드를 읽어 추측하면
    현재 구현을 명세로 승격시키는 것이므로 순환이다.
    """
    checks: list[Check] = []
    for p in _source_files(root, cfg):
        text = _read(p)
        rel = _rel(p, root)
        if _FORM_RE.search(text):
            checks.append(Check(
                kind="form-rules",
                claim=f"{p.stem} 의 입력 검증 규칙",
                declared_at=rel,
                verdict="needs-intent", auto=False,
                detail="폼/제출 핸들러가 있습니다. **무엇을 거부해야 하는가**는 코드에 "
                       "선언되어 있지 않습니다 — 현재 구현을 읽어 명세로 올리면 순환입니다",
            ))
        if _AWAIT_RE.search(text) and not _CATCH_RE.search(text):
            checks.append(Check(
                kind="error-path",
                claim=f"{p.stem} 의 실패 시 동작",
                declared_at=rel,
                verdict="needs-intent", auto=False,
                detail="await 가 있는데 오류 처리 분기가 없습니다. 실패 시 무엇을 "
                       "보여야 하는가는 의도입니다 (조용히 무시하는 것도 선택일 수 있습니다)",
            ))
    return checks


# ── 게이트 준비 상태 ─────────────────────────────────────────────────────────

def assess_readiness(root: Path, cfg: ProjectConfig, harness_root: str | Path) -> Readiness:
    """하네스를 붙일 수 있는가. 막는 것을 전부 열거한다."""
    from harness import runner as runner_mod
    from harness.tags import scan_tags

    r = Readiness(runner=cfg.runner)
    try:
        runner = runner_mod.for_project(cfg, harness_root)
        r.runner_runnable, r.runner_note = runner.available()
    except ValueError as exc:
        r.runner_runnable, r.runner_note = False, str(exc)

    tests = _test_files(root, cfg)
    r.test_files = len(tests)

    spec_path = cfg.spec_path(harness_root)
    r.spec_exists = spec_path.is_file()
    if r.spec_exists:
        try:
            data = json.loads(spec_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = []
        if isinstance(data, list):
            r.spec_features = len(data)
            id_re = cfg.id_regex()
            r.spec_ids_matching = sum(
                1 for f in data
                if isinstance(f, dict) and id_re.fullmatch(str(f.get("id", "")))
            )

    try:
        refs = scan_tags(str(root), cfg)
        r.tagged_features = len({ref.feature_id for ref in refs if ref.kind == "unit"})
    except Exception:                                  # noqa: BLE001 — 검수는 멈추지 않는다
        r.tagged_features = 0

    if not r.runner_runnable:
        r.blockers.append(
            f"런너({cfg.runner})를 실행할 수 없습니다. {r.runner_note}"
        )
    if r.test_files == 0:
        r.blockers.append(
            "테스트 파일이 0개입니다. 증거 게이트는 '기능 ID 를 인용하는 통과 테스트'를 "
            "요구하므로 지금 붙이면 모든 기능이 거부됩니다 — 설계대로 동작하는 것이지만 "
            "쓸 수는 없습니다"
        )
    if not r.spec_exists:
        r.blockers.append(
            f"명세({cfg.spec})가 없습니다. 이것이 사람이 채워야 하는 유일한 입력입니다 "
            f"— 아래 '의도가 필요한 후보'가 출발점입니다"
        )
    elif r.spec_features and r.spec_ids_matching == 0:
        r.blockers.append(
            f"명세의 ID 가 id_pattern({cfg.id_pattern})과 하나도 맞지 않습니다. "
            f".harness.json 의 id_pattern 을 고치십시오"
        )
    return r


# ── 명세 초안 ────────────────────────────────────────────────────────────────

#: 검수 항목 중 **기능이 아닌 것** — 코드 위생 규칙이다 (TS-028).
#:
#: "모든 소스가 테스트에서 import 된다", "export 가 참조된다" 는 사용자가 관찰할
#: 수 있는 행동이 아니고 `steps` 를 채울 수도 없다. `features.json` 에 넣으면
#: 게이트가 기능 아닌 것을 기능으로 센다. 검수 보고(`checks`)에 남고 초안에서는 뺀다.
NOT_FEATURES = frozenset({"untested-source", "unreferenced-export", "dead-script"})


def draft_spec(root: Path, cfg: ProjectConfig, checks: list[Check],
               existing: list[dict[str, Any]] | None = None
               ) -> tuple[list[dict[str, Any]], list[Any]]:
    """명세 **초안**과 **질문**을 만든다. (초안 목록, 질문 목록)

    초안은 `features.draft.json` 에만 쓴다 — `features.json` 에 직접 넣으면 하네스가
    자기가 코드에서 뽑은 명세로 그 코드를 검사하게 되어 순환이다 (TS-013).
    각 항목에는 `origin` 과 `needs_review` 를 박아 출처를 지운 채 섞이지 않게 한다.

    이전 구현은 **검수 발견 사항을 기능처럼 포장**했다 (TS-028). 실측한 4건 중 둘은
    코드 위생 규칙이고 둘은 내용 없는 주제였으며, ID 가 `F-001` 부터 시작해 기존
    명세와 **충돌**했다. 지금은 셋으로 나눈다:

      초안   `harness/draft.py` 가 **선언**에서 뽑은 행동 명세 (검증 지점이 다르다)
      질문   명세가 필요하지만 내용이 **구현에만** 있는 자리 — 사람이 결정할 것
      제외   코드 위생 규칙 — 검수 보고에 남기고 초안에 넣지 않는다
    """
    from harness.draft import (
        DraftQuestion,
        draft_from_declarations,
        extract_declarations,
    )

    existing = existing or []
    decls = extract_declarations(root, cfg)
    specs = draft_from_declarations(decls, existing, cfg.id_pattern)

    questions: list[Any] = []
    for c in checks:
        if c.kind in NOT_FEATURES:
            continue                        # 기능이 아니다 — 검수 보고에만 남는다
        if c.auto and c.verdict == "ok":
            continue                        # 이미 통과한 불변식은 명세로 올릴 필요가 없다
        if c.verdict == "needs-intent":
            questions.append(DraftQuestion(
                topic=c.claim,
                where=c.implemented_at or c.declared_at or "위치 불명",
                decision=c.detail or "무엇이 올바른 동작인지",
                why_not_drafted=("답이 코드의 **제어 흐름**에만 있습니다. 읽어서 "
                                 "명세로 올리면 그 구현을 그 구현으로 검사하는 "
                                 "**순환**이 됩니다 (TS-013)"),
            ))
    return [s.to_feature() for s in specs], questions


# ── 진입점 ───────────────────────────────────────────────────────────────────

def inspect_project(harness_root: str | Path, cfg: ProjectConfig | None = None,
                    findings: list[project.Finding] | None = None) -> Report:
    """전체 검수. 아무것도 실행하지 않고 파일만 읽는다 (런너 가용성 확인은 예외)."""
    harness_root = Path(harness_root).resolve()
    if cfg is None:
        cfg, findings = project.load(harness_root)
    root = cfg.target_path(harness_root)

    checks: list[Check] = []
    checks += check_dead_scripts(root)
    checks += check_route_completeness(root, cfg)
    checks += check_untested_sources(root, cfg)
    checks += check_unreferenced_exports(root, cfg)
    intent = candidates_needing_intent(root, cfg)

    report = Report(
        cfg=cfg,
        findings=findings or [],
        readiness=assess_readiness(root, cfg, harness_root),
        checks=checks + intent,
    )
    # 기존 명세를 넘겨 ID 충돌을 피한다 — 이전 구현은 F-001 부터 내서 겹쳤다 (TS-028)
    try:
        existing = json.loads(
            (root / "features.json").read_text(encoding="utf-8")
        ) if (root / "features.json").is_file() else []
    except (json.JSONDecodeError, OSError):
        existing = []
    if not existing:
        # 이 레포의 배치: 명세는 하네스 루트, 앱은 target/ 아래다
        fp = harness_root / "features.json"
        try:
            existing = json.loads(fp.read_text(encoding="utf-8")) if fp.is_file() else []
        except (json.JSONDecodeError, OSError):
            existing = []
    report.draft, report.questions = draft_spec(root, cfg, report.checks, existing)
    return report


def format_report(report: Report, harness_root: str | Path) -> str:
    bar = "=" * 72
    cfg, r = report.cfg, report.readiness
    auto = [c for c in report.checks if c.auto]
    violated = [c for c in auto if c.verdict == "violated"]
    advisory = [c for c in auto if c.verdict == "advisory"]
    passed = [c for c in auto if c.verdict == "ok"]
    intent = [c for c in report.checks if not c.auto]

    lines = [bar, f"프로젝트 검수 — {cfg.target_path(harness_root)}", bar, ""]

    lines += ["  [1] 게이트 준비 상태", "  " + "-" * 68]
    lines.append(f"    런너        {cfg.runner} — " +
                 ("실행 가능" if r.runner_runnable else f"실행 불가 ({r.runner_note.strip()})"))
    lines.append(f"    테스트 파일  {r.test_files}개")
    lines.append(f"    명세        " + (
        f"{cfg.spec} — 기능 {r.spec_features}개 (ID 형식 일치 {r.spec_ids_matching}개)"
        if r.spec_exists else f"{cfg.spec} — 없음"))
    lines.append(f"    태그된 기능  {r.tagged_features}개")
    lines.append("")
    if r.attachable():
        lines.append("    → 지금 바로 붙일 수 있습니다. `cli audit` 으로 시작하십시오.")
    else:
        lines.append(f"    → 붙기 전에 해결할 것 {len(r.blockers)}건:")
        for i, b in enumerate(r.blockers, 1):
            lines.append(f"       {i}. {b}")
    lines.append("")

    lines += [f"  [2] 자동 판정 — 의도 없이 객관적으로 결정되는 검사 ({len(auto)}건)",
              "  " + "-" * 68]
    if not auto:
        lines.append("    추출된 불변식이 없습니다 (소스 디렉터리 설정을 확인하십시오).")
    else:
        lines.append(f"    위반 {len(violated)} · 권고 {len(advisory)} · 통과 {len(passed)}")
        lines.append("")
        for group in (violated, advisory, passed):
            for c in group:
                lines.append(c.line())
            if group:
                lines.append("")
        # 위반과 권고를 가르는 기준을 **출력에 적는다** (TS-029). 적지 않으면
        # 다음 사람이 "권고도 위반인데 왜 안 막나"로 읽고 다시 합친다.
        lines.append("    위반 = 차단 근거가 서는 판정 (검사기에 맹점이 없다) → 종료 코드 1")
        lines.append("    권고 = 사실이지만 검사기에 **알려진 맹점**이 있다 → 차단하지 않는다")
    lines.append("")

    lines += [f"  [3] 의도가 필요한 후보 — 제가 정할 수 없는 것 ({len(intent)}건)",
              "  " + "-" * 68]
    if not intent:
        lines.append("    없습니다.")
    else:
        seen: set[str] = set()
        for c in intent:
            key = f"{c.kind}:{c.declared_at}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(c.line())
    lines += [
        "",
        "  " + "-" * 68,
        "  해석:",
        "    [2] 는 **선언과 구현의 일치**를 봅니다. 두 지점이 서로 다른 파일에 있으므로",
        "        어느 한쪽이 틀리면 잡힙니다 — 의도를 몰라도 판정됩니다.",
        "    [3] 은 코드 어디에도 답이 적혀 있지 않습니다. 제가 현재 구현을 읽어 명세로",
        "        올리면 그 구현을 그 구현으로 검사하는 순환이 됩니다 (TS-013).",
    ]
    # 초안과 질문을 **나눠서** 보고한다 (TS-028). 이전에는 검수 발견 사항을 기능처럼
    # 포장해 섞어 냈고, 그중 둘은 코드 위생 규칙이라 `steps` 를 채울 수도 없었다.
    if report.draft:
        lines += [
            f"    초안 {len(report.draft)}건 — **선언에서 뽑은 행동 명세**입니다.",
            "        `cli inspect --write-draft` 로 features.draft.json 에 씁니다.",
            "        각 항목에 읽은 선언의 원문과 위치가 붙어 있습니다 — 선언 자체가",
            "        틀렸다면 초안도 틀리므로 그 판단은 사람이 해야 합니다.",
        ]
    else:
        lines.append("    초안 0건 — 뽑을 상태 조건부 선언을 찾지 못했습니다.")
    if report.questions:
        lines += [
            f"    질문 {len(report.questions)}건 — 명세가 필요하지만 내용이 **구현에만**",
            "        있습니다. 초안으로 내지 않습니다 (읽어서 올리면 순환입니다).",
        ]
    lines += [
        "    코드 위생 규칙(미테스트 소스·미참조 export)은 **기능이 아니므로** 초안에",
        "        넣지 않습니다 — 위 [2] 에만 남습니다.",
        bar,
    ]
    return "\n".join(lines)

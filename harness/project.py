"""
harness/project.py
──────────────────
**프로젝트 설정의 외부화와 자동 검수.**

배경:
  TS-005~TS-016 까지의 실패 양식(failure mode)은 생태계와 무관하다 — 자기 채점,
  공허한 증거, 태그 오귀속, 측정 고아화는 jest 든 pytest 든 똑같이 일어난다.
  그런데 그 양식을 **집행하는** 코드에는 `web_target`, `jest`, `.test.tsx`,
  `F-\\d{3}` 이 박혀 있었다. 그래서 하네스가 이 레포 한 곳에만 붙었다.

  이 모듈은 그 네 가지를 **프로젝트가 선언하는 값**으로 끌어낸다.
  선언이 없으면 **검수해서 추론하고, 추론의 근거를 함께 보고한다.**

왜 추론에 근거를 붙이는가:
  "자동 감지했습니다"만 출력하면 틀렸을 때 사용자가 알 수 없다. 이 프로젝트의
  모든 측정이 그랬다(TS-009/TS-016). 그래서 `Finding` 에 **무엇을 보고 그렇게
  판단했는지**를 담아 함께 출력한다. 추론은 틀릴 수 있고, 틀렸을 때 사용자가
  `.harness.json` 에 한 줄 적어 덮을 수 있어야 한다.

해석 주의:
  이 모듈이 정하는 것은 **어떻게 검사하는가**(런너·규약·경로)이지
  **무엇이 되어야 하는가**(의도)가 아니다. 후자는 `harness/inspect.py` 가
  후보를 뽑되 사람의 승인을 요구한다. 코드에서 의도를 길어내 그 코드를 검사하면
  순환이다 (TS-013).
"""

from __future__ import annotations

import json
import os
import re
from fnmatch import fnmatch
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: 설정 파일 이름 — 하네스 루트 또는 대상 프로젝트 루트에 둔다
CONFIG_NAME = ".harness.json"

#: 검수 시 절대 들어가지 않는 디렉터리.
#: 근거 (TS-006): rootDir 을 추정하게 두면 jest 가 사용자 홈의 .vscode/extensions 까지
#: 스캔하며 2분을 태웠다. 검수도 같은 함정을 가진다 — 범위를 먼저 못 박는다.
SKIP_DIRS = frozenset({
    "node_modules", ".git", "dist", "build", "out", "coverage", ".next",
    ".nuxt", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".harness_memory", "playwright-report", "test-results", ".turbo", ".cache",
})

#: 생태계별 기본값. 선언도 없고 실측도 불가능할 때만 쓴다.
ECOSYSTEM_DEFAULTS: dict[str, dict[str, Any]] = {
    "jest": {
        "unit_suffixes": [".test.ts", ".test.tsx", ".test.js", ".test.jsx"],
        "e2e_suffixes": [".spec.ts", ".spec.tsx", ".e2e.ts"],
        "source_dirs": ["src"],
    },
    "vitest": {
        "unit_suffixes": [".test.ts", ".test.tsx", ".test.js", ".test.jsx"],
        "e2e_suffixes": [".spec.ts", ".spec.tsx", ".e2e.ts"],
        "source_dirs": ["src"],
    },
    # pytest 의 관례는 **접두사**다. 접미사로만 쓰면 `test_app.py` 가 매칭되지 않는다
    # (TS-025 에서 실측). 글로브로 적어야 한다 — `tags.matches_pattern` 이 처리한다.
    "pytest": {
        "unit_suffixes": ["test_*.py", "*_test.py"],
        "e2e_suffixes": ["*_e2e.py", "e2e_*.py"],
        "source_dirs": ["src", "."],
    },
}


def walk_files(root: str | Path, skip_dirs: frozenset[str] | set[str],
               suffixes: tuple[str, ...] | None = None) -> list[Path]:
    """파일을 걷는다. **건너뛸 디렉터리에는 들어가지 않는다** (TS-030).

    `Path.rglob("*")` 은 `node_modules` 와 `.venv` **안까지 전부 걷고 나서** 필터한다.
    실측: `web_target/node_modules` 에 항목이 **17,721개**이고 걷는 데 1.08초다.
    `_test_files` 가 inspect 안에서 세 번 불리므로 그것만 4초가 넘었고,
    `cli exposure` 가 22초, `repro_ts027` 이 3분 13초였다.

    `os.walk` 는 `dirnames` 를 제자리에서 비우면 그 아래로 내려가지 않는다.
    같은 결과를 내면서 걷는 양이 줄어든다 — 동작이 아니라 **비용**만 바뀐다.
    """
    out: list[Path] = []
    base = Path(root)
    for dirpath, dirnames, filenames in os.walk(base):
        # 제자리 수정이 중요하다. 새 리스트를 대입하면 os.walk 가 못 본다.
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        here = Path(dirpath)
        for name in filenames:
            if suffixes is None or name.endswith(suffixes):
                out.append(here / name)
    return out


def matches_pattern(name: str, patterns: tuple[str, ...]) -> bool:
    """파일명이 규약 중 하나에 맞는가 — 접미사와 글로브를 모두 받는다 (TS-025).

    왜 접미사만으로는 안 되는가 — 실측:
      pytest 의 관례는 **접두사**다(`test_app.py`). 접미사 비교만 하면
      `name.endswith("test_.py")` 가 되어 `test_app.py` 가 **테스트로 인식되지 않는다.**
      그 결과 관례적 이름을 쓰는 pytest 프로젝트에서는 `tagged_test_files` 가 빈
      목록을 돌려주고 게이트가 모든 기능을 거부한다. 기본값이 그 깨진 값
      (`"test_.py"`)을 담고 있었고, 검수(`_detect_suffixes`)가 그것을 **생산**했다.

      pytest 경로는 "단위 검증으로만 확인했다"고 README 에 적혀 있었고, 그 단위
      검증이 `_test.py` 형태만 썼기 때문에 통과했다 — 단일 모양으로 검증하면
      다른 모양이 존재한다는 사실 자체가 테스트에 없다.

    왜 `project.py` 에 있는가 — 호출자가 넷이고, 그중 셋이 각자 `endswith` 로
    따로 구현해 **셋 다 pytest 에서 틀렸다** (`independence._declared_collections`,
    `inspect._source_files`/`_test_files`, `runner._is_source`). 규약 판정은
    설정의 책임이므로 설정이 사는 이 파일에 둔다. `tags` 는 이것을 재노출한다.

    규칙:
      `*` 나 `?` 가 있으면 글로브(`test_*.py`), 없으면 접미사(`.test.ts`).
      접미사 동작을 유지하므로 기존 `.harness.json` 은 그대로 작동한다.
    """
    for pat in patterns:
        if "*" in pat or "?" in pat:
            if fnmatch(name, pat):
                return True
        elif name.endswith(pat):
            return True
    return False


@dataclass
class Finding:
    """검수 결과 한 줄 — 무엇을 정했고, 무엇을 보고 그렇게 정했는지."""

    key: str
    value: str
    source: str      # 'declared' | 'measured' | 'default'
    evidence: str

    def line(self) -> str:
        mark = {"declared": "선언", "measured": "실측", "default": "기본"}
        return f"  [{mark.get(self.source, self.source)}] {self.key} = {self.value}\n         └ {self.evidence}"


@dataclass
class ProjectConfig:
    """하네스가 한 프로젝트를 검사하는 데 필요한 전부.

    `target` 만 프로젝트 **구조**에 관한 것이고 나머지는 **규약**이다.
    모든 필드는 `.harness.json` 으로 덮을 수 있다.
    """

    #: 검사 대상 앱의 경로 (하네스 루트 기준 상대, 또는 절대)
    target: str = "web_target"
    #: 테스트 런너 — jest | vitest | pytest
    runner: str = "jest"
    #: 명세 파일 (target 기준 상대 — 하네스 루트에 있으면 '../features.json')
    spec: str = "features.json"
    #: 기능 ID 정규식. 캡처 그룹 없이 쓸 것 (태그 스캐너가 그대로 쓴다)
    id_pattern: str = r"F-\d{3}"
    #: 단위 테스트로 인정하는 파일 접미사 — 증거로 계수된다
    unit_suffixes: list[str] = field(default_factory=lambda: [".test.ts", ".test.tsx"])
    #: E2E 로 인정하는 접미사 — 게이트 증거로는 계수하지 않는다(런너가 다르다)
    e2e_suffixes: list[str] = field(default_factory=lambda: [".spec.ts", ".spec.tsx"])
    #: 소스 디렉터리 (커버리지 귀속·검수 범위)
    source_dirs: list[str] = field(default_factory=lambda: ["src"])
    #: 타입/정적 검사 커맨드. 빈 목록이면 돌연변이 유효성 확인을 건너뛴다
    typecheck: list[str] = field(default_factory=list)

    # ── 파생 ────────────────────────────────────────────────────────────────

    def target_path(self, harness_root: str | Path) -> Path:
        p = Path(self.target)
        return p.resolve() if p.is_absolute() else (Path(harness_root) / p).resolve()

    def spec_path(self, harness_root: str | Path) -> Path:
        p = Path(self.spec)
        if p.is_absolute():
            return p.resolve()
        # 대상 기준으로 먼저 찾고, 없으면 하네스 루트에서 찾는다.
        # 근거: 이 레포는 명세를 하네스 루트에 두고 앱을 web_target/ 에 두는 배치다.
        candidate = self.target_path(harness_root) / p
        if candidate.is_file():
            return candidate.resolve()
        return (Path(harness_root) / p).resolve()

    def all_test_suffixes(self) -> tuple[str, ...]:
        return tuple(self.unit_suffixes) + tuple(self.e2e_suffixes)

    def is_test_file(self, name: str) -> bool:
        """이 파일이 선언된 테스트 규약에 맞는가. **파일명도 경로도 받는다.**

        `name.endswith(cfg.all_test_suffixes())` 를 **직접 쓰지 말 것** — 규약은
        글로브일 수 있다(`test_*.py`). 그렇게 쓴 세 곳이 pytest 에서 전부
        틀렸다 (TS-025).

        경로를 받아 파일명만 떼는 이유: 호출자 중 둘은 파일명(`p.name`)을 주고
        하나(`runner._is_source`)는 커버리지가 뱉은 **경로**(`tests/test_convert.py`)를
        준다. 접미사 비교는 경로에서도 맞았지만 글로브는 맞지 않는다 —
        `fnmatch("tests/test_convert.py", "test_*.py")` 는 거짓이다. 정규화를 여기서
        하면 호출자마다 기억해야 할 규칙이 하나 줄고, 접미사 동작은 바뀌지 않는다
        (파일명에 대한 `endswith` 결과는 경로에 대한 것과 같다).
        """
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        return matches_pattern(base, self.all_test_suffixes())

    def id_regex(self) -> re.Pattern[str]:
        return re.compile(self.id_pattern)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── 설정 파일 ────────────────────────────────────────────────────────────────

def load(harness_root: str | Path, *, detect_if_missing: bool = True
         ) -> tuple[ProjectConfig, list[Finding]]:
    """`.harness.json` 을 읽는다. 없으면 검수해서 추론한다.

    Returns:
        (설정, 검수 내역). 내역은 사람에게 보여주기 위한 것이며 판정에 쓰지 않는다.
    """
    root = Path(harness_root).resolve()
    path = root / CONFIG_NAME
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # 설정이 깨졌으면 조용히 기본값으로 떨어지지 않는다 — 그게 TS-007 이었다
            # (죽은 설정이 조용히 무시되어 아무도 몰랐다).
            raise ValueError(f"{path} 를 읽을 수 없습니다: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{path} 의 최상위는 객체여야 합니다.")
        known = {f for f in ProjectConfig().to_dict()}
        unknown = sorted(set(raw) - known)
        cfg = ProjectConfig(**{k: v for k, v in raw.items() if k in known})
        findings = [
            Finding(k, json.dumps(raw[k], ensure_ascii=False), "declared", f"{CONFIG_NAME}")
            for k in sorted(raw) if k in known
        ]
        if unknown:
            findings.append(Finding(
                "(무시됨)", ", ".join(unknown), "declared",
                f"{CONFIG_NAME} 에 하네스가 모르는 키가 있습니다 — 오타일 수 있습니다",
            ))
        # 선언이 비운 칸은 추론으로 메운다 (부분 선언 허용)
        if detect_if_missing:
            guessed, more = detect(cfg.target_path(root))
            for key in ("runner", "unit_suffixes", "e2e_suffixes", "source_dirs", "typecheck"):
                if key not in raw:
                    setattr(cfg, key, getattr(guessed, key))
                    findings += [f for f in more if f.key == key]
        return cfg, findings

    if not detect_if_missing:
        return ProjectConfig(), []

    # 설정 파일이 없다 — 대상 후보를 찾고 검수한다
    target, target_finding = _guess_target(root)
    cfg, findings = detect(target)
    cfg.target = _relative_to(target, root)
    findings.insert(0, target_finding)
    spec, spec_finding = _guess_spec(root, target)
    if spec:
        cfg.spec = spec
    findings.append(spec_finding)
    pattern, pat_finding = _guess_id_pattern(cfg.spec_path(root))
    if pattern:
        cfg.id_pattern = pattern
    findings.append(pat_finding)
    return cfg, findings


def save(cfg: ProjectConfig, harness_root: str | Path) -> Path:
    """`.harness.json` 을 쓴다. 이미 있으면 덮지 않고 예외를 던진다."""
    path = Path(harness_root).resolve() / CONFIG_NAME
    if path.exists():
        raise FileExistsError(f"{path} 가 이미 있습니다. 덮어쓰려면 직접 편집하십시오.")
    path.write_text(
        json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# ── 검수 (detection) ─────────────────────────────────────────────────────────

def detect(target: str | Path) -> tuple[ProjectConfig, list[Finding]]:
    """대상 프로젝트를 읽어 런너와 규약을 추론한다. 파일만 읽고 아무것도 실행하지 않는다."""
    root = Path(target).resolve()
    findings: list[Finding] = []

    runner, runner_finding = _detect_runner(root)
    findings.append(runner_finding)

    defaults = ECOSYSTEM_DEFAULTS.get(runner, ECOSYSTEM_DEFAULTS["jest"])
    cfg = ProjectConfig(runner=runner, **{k: list(v) for k, v in defaults.items()})

    units, e2es, suffix_findings = _detect_suffixes(root, runner)
    if units:
        cfg.unit_suffixes = units
    if e2es:
        cfg.e2e_suffixes = e2es
    findings += suffix_findings

    dirs, dir_finding = _detect_source_dirs(root)
    cfg.source_dirs = dirs
    findings.append(dir_finding)

    tc, tc_finding = _detect_typecheck(root, runner)
    cfg.typecheck = tc
    findings.append(tc_finding)

    return cfg, findings


def _package_json(root: Path) -> dict[str, Any]:
    pkg = root / "package.json"
    if not pkg.is_file():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _detect_runner(root: Path) -> tuple[str, Finding]:
    """런너를 추론한다. 의존성 선언 > 설정 파일 > 생태계 추정 순.

    의존성을 먼저 보는 이유: 설정 파일은 남아 있어도 패키지가 제거된 경우가 있다
    (TS-012 에서 죽은 npm 스크립트 3개를 실측했다). 실제로 돌 수 있는지가 기준이다.
    """
    pkg = _package_json(root)
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

    if "vitest" in deps:
        return "vitest", Finding("runner", "vitest", "measured",
                                 "package.json 의 의존성에 vitest 가 있습니다")
    if "jest" in deps:
        return "jest", Finding("runner", "jest", "measured",
                               "package.json 의 의존성에 jest 가 있습니다")

    for name in ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"):
        if (root / name).is_file():
            return "vitest", Finding("runner", "vitest", "measured",
                                     f"{name} 이 있습니다 (의존성 선언은 없음 — npm install 필요할 수 있습니다)")
    for name in ("jest.config.ts", "jest.config.js", "jest.config.mjs",
                 "jest.config.cjs", "jest.config.json"):
        if (root / name).is_file():
            return "jest", Finding("runner", "jest", "measured",
                                   f"{name} 이 있습니다 (의존성 선언은 없음 — npm install 필요할 수 있습니다)")
    if "jest" in pkg:
        return "jest", Finding("runner", "jest", "measured",
                               "package.json 에 jest 설정 블록이 있습니다")

    # 파이썬
    for name in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
        p = root / name
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "pytest" in text:
                return "pytest", Finding("runner", "pytest", "measured",
                                         f"{name} 에 pytest 설정이 있습니다")
    if list(root.glob("test_*.py")) or list(root.glob("tests/test_*.py")):
        return "pytest", Finding("runner", "pytest", "measured",
                                 "test_*.py 파일이 있습니다")

    # 아무 증거도 없다 — 생태계만 보고 **제안**한다
    if (root / "vite.config.ts").is_file() or (root / "vite.config.js").is_file():
        return "vitest", Finding(
            "runner", "vitest", "default",
            "테스트 프레임워크가 설치되어 있지 않습니다. Vite 프로젝트이므로 vitest 를 "
            "제안합니다 (설정을 공유합니다). 설치 전에는 게이트가 모든 기능을 거부합니다",
        )
    if pkg:
        return "jest", Finding(
            "runner", "jest", "default",
            "테스트 프레임워크가 설치되어 있지 않습니다. JS 프로젝트이므로 jest 를 "
            "기본값으로 둡니다. 설치 전에는 게이트가 모든 기능을 거부합니다",
        )
    return "jest", Finding(
        "runner", "jest", "default",
        "런너를 추론할 근거가 없습니다 (package.json·pyproject.toml 둘 다 없음). "
        f"{CONFIG_NAME} 에 runner 를 직접 적으십시오",
    )


def _iter_files(root: Path, limit: int = 20000):
    """SKIP_DIRS 를 피해 파일을 순회한다. 상한을 두어 거대 레포에서 멈추지 않게 한다."""
    count = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
                continue
            count += 1
            if count > limit:
                return
            yield entry


def _detect_suffixes(root: Path, runner: str) -> tuple[list[str], list[str], list[Finding]]:
    """실제로 존재하는 테스트 파일에서 접미사 규약을 **실측**한다.

    근거: 규약은 프로젝트마다 다르다(`.test.tsx` / `.spec.ts` / `_test.py`).
    기본값을 믿지 않고 세어 본다. 하나도 없으면 빈 목록을 반환해 호출자가
    생태계 기본값을 쓰게 한다.
    """
    unit_candidates = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".test.mjs",
                       ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx")
    counts: dict[str, int] = {}
    py_test = 0
    e2e_dirs: dict[str, int] = {}

    for f in _iter_files(root):
        name = f.name
        if runner == "pytest":
            if name.startswith("test_") and name.endswith(".py"):
                py_test += 1
            elif name.endswith("_test.py"):
                counts["_test.py"] = counts.get("_test.py", 0) + 1
            continue
        for suffix in unit_candidates:
            if name.endswith(suffix):
                counts[suffix] = counts.get(suffix, 0) + 1
                # E2E 는 디렉터리로도 갈린다 (e2e/, tests/, playwright/)
                parts = {p.lower() for p in f.relative_to(root).parts[:-1]}
                if parts & {"e2e", "playwright", "cypress", "integration"}:
                    e2e_dirs[suffix] = e2e_dirs.get(suffix, 0) + 1
                break

    if runner == "pytest":
        found = []
        if py_test:
            found.append("test_*.py")        # 접두사 규약 — 글로브로 적는다 (TS-025)
        if counts.get("_test.py"):
            found.append("*_test.py")
        if not found:
            return [], [], [Finding("unit_suffixes", "(생태계 기본값)", "default",
                                    "테스트 파일을 찾지 못했습니다")]
        return found, [], [Finding(
            "unit_suffixes", ", ".join(found), "measured",
            f"test_*.py {py_test}개, *_test.py {counts.get('_test.py', 0)}개 발견",
        )]

    if not counts:
        return [], [], [Finding(
            "unit_suffixes", "(생태계 기본값)", "default",
            "테스트 파일을 하나도 찾지 못했습니다 — 증거를 만들 수 없으므로 "
            "게이트가 모든 기능을 거부합니다",
        )]

    # `.spec.*` 이 E2E 디렉터리에만 있으면 E2E 규약, 섞여 있으면 단위에도 넣는다.
    units: list[str] = []
    e2es: list[str] = []
    detail: list[str] = []
    for suffix, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        in_e2e = e2e_dirs.get(suffix, 0)
        detail.append(f"{suffix} {n}개" + (f" (그중 E2E 경로 {in_e2e}개)" if in_e2e else ""))
        if in_e2e and in_e2e == n:
            e2es.append(suffix)
        else:
            units.append(suffix)

    findings = [Finding("unit_suffixes", ", ".join(units) or "(없음)", "measured",
                        "실측: " + ", ".join(detail))]
    if e2es:
        findings.append(Finding(
            "e2e_suffixes", ", ".join(e2es), "measured",
            "E2E 전용 경로에만 있어 증거로 계수하지 않습니다 (런너가 다릅니다)",
        ))
    return units, e2es, findings


def _detect_source_dirs(root: Path) -> tuple[list[str], Finding]:
    """소스 디렉터리를 찾는다."""
    preferred = ["src", "app", "lib", "components", "pages"]
    found = [d for d in preferred if (root / d).is_dir()]
    if found:
        return found, Finding("source_dirs", ", ".join(found), "measured",
                              "해당 디렉터리가 존재합니다")
    tops = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
    ) if root.is_dir() else []
    if tops:
        return tops[:4], Finding(
            "source_dirs", ", ".join(tops[:4]), "default",
            "관례적 소스 디렉터리(src/app/lib)가 없어 최상위 디렉터리를 씁니다",
        )
    return ["."], Finding("source_dirs", ".", "default",
                          "하위 디렉터리가 없어 루트를 소스로 봅니다")


def _detect_typecheck(root: Path, runner: str) -> tuple[list[str], Finding]:
    """정적 검사 커맨드. 돌연변이 유효성 확인에 쓴다 (없으면 그 단계를 건너뛴다)."""
    if runner in ("jest", "vitest"):
        if (root / "tsconfig.json").is_file():
            return ["npx", "--no-install", "tsc", "--noEmit"], Finding(
                "typecheck", "tsc --noEmit", "measured", "tsconfig.json 이 있습니다")
        return [], Finding(
            "typecheck", "(없음)", "default",
            "tsconfig.json 이 없습니다 — 돌연변이의 유효성 확인을 건너뜁니다"
            " (깨진 변이가 '잡혔다'로 계수될 수 있어 점수가 과대평가됩니다)",
        )
    if runner == "pytest":
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "mypy" in pyproject.read_text(encoding="utf-8", errors="replace"):
                    return ["mypy", "."], Finding(
                        "typecheck", "mypy .", "measured", "pyproject.toml 에 mypy 설정이 있습니다")
            except OSError:
                pass
        return [], Finding("typecheck", "(없음)", "default", "mypy 설정을 찾지 못했습니다")
    return [], Finding("typecheck", "(없음)", "default", "런너를 모릅니다")


def _relative_to(path: Path, base: Path) -> str:
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return str(path.resolve())
    return str(rel).replace("\\", "/") or "."


def _guess_target(harness_root: Path) -> tuple[Path, Finding]:
    """검사 대상 앱을 찾는다. 하네스 루트 자체일 수도, 하위 디렉터리일 수도 있다."""
    if (harness_root / "package.json").is_file() or (harness_root / "pyproject.toml").is_file():
        return harness_root, Finding(
            "target", ".", "measured",
            "하네스 루트에 package.json/pyproject.toml 이 있어 루트를 대상으로 봅니다")
    candidates = [
        d for d in sorted(harness_root.iterdir())
        if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
        and ((d / "package.json").is_file() or (d / "pyproject.toml").is_file())
    ] if harness_root.is_dir() else []
    if len(candidates) == 1:
        return candidates[0], Finding(
            "target", candidates[0].name, "measured",
            f"하위 디렉터리 중 {candidates[0].name} 만 패키지 매니페스트를 가집니다")
    if candidates:
        pick = candidates[0]
        return pick, Finding(
            "target", pick.name, "default",
            f"후보가 {len(candidates)}개입니다 ({', '.join(c.name for c in candidates)}) — "
            f"{pick.name} 을 골랐습니다. 다르면 {CONFIG_NAME} 의 target 을 고치십시오",
        )
    return harness_root, Finding(
        "target", ".", "default",
        "패키지 매니페스트를 찾지 못해 루트를 대상으로 둡니다")


def _guess_spec(harness_root: Path, target: Path) -> tuple[str | None, Finding]:
    """명세 파일을 찾는다."""
    for name in ("features.json", "spec.json", ".harness/features.json"):
        if (target / name).is_file():
            return name, Finding("spec", name, "measured", f"{target.name}/{name} 이 있습니다")
        if (harness_root / name).is_file():
            rel = _relative_to(harness_root / name, target)
            return rel, Finding("spec", rel, "measured", f"하네스 루트의 {name} 을 씁니다")
    return None, Finding(
        "spec", "features.json", "default",
        "명세 파일이 없습니다 — 이것이 사람이 채워야 하는 유일한 입력입니다. "
        "`cli inspect` 로 후보를 뽑을 수 있습니다",
    )


def _guess_id_pattern(spec_path: Path) -> tuple[str | None, Finding]:
    """명세에 실제로 쓰인 ID 에서 형식을 추론한다."""
    if not spec_path.is_file():
        return None, Finding("id_pattern", r"F-\d{3}", "default",
                             "명세가 없어 기본 형식을 씁니다")
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, Finding("id_pattern", r"F-\d{3}", "default",
                             f"명세를 파싱할 수 없습니다 ({exc}) — 기본 형식을 씁니다")
    ids = [str(f.get("id", "")) for f in data if isinstance(f, dict)] if isinstance(data, list) else []
    ids = [i for i in ids if i]
    if not ids:
        return None, Finding("id_pattern", r"F-\d{3}", "default",
                             "명세에 id 필드가 없습니다")
    m = re.fullmatch(r"([A-Za-z]+)[-_]?(\d+)", ids[0])
    if not m:
        return None, Finding(
            "id_pattern", r"F-\d{3}", "default",
            f"ID {ids[0]!r} 가 '접두사+숫자' 형태가 아닙니다 — 정규식을 직접 적으십시오")
    prefix, digits = m.group(1), m.group(2)
    sep = ids[0][len(prefix):len(ids[0]) - len(digits)]
    pattern = re.escape(prefix) + re.escape(sep) + r"\d{" + str(len(digits)) + "}"
    matched = sum(1 for i in ids if re.fullmatch(pattern, i))
    return pattern, Finding(
        "id_pattern", pattern, "measured",
        f"명세의 ID {len(ids)}개 중 {matched}개가 이 형식입니다 (예: {ids[0]})",
    )


def format_findings(cfg: ProjectConfig, findings: list[Finding], harness_root: str | Path) -> str:
    """검수 결과를 사람이 읽을 형태로."""
    bar = "=" * 70
    lines = [bar, "프로젝트 검수 — 하네스가 무엇을 어떻게 검사할지", bar, ""]
    for f in findings:
        lines.append(f.line())
    declared = sum(1 for f in findings if f.source == "declared")
    measured = sum(1 for f in findings if f.source == "measured")
    default = sum(1 for f in findings if f.source == "default")
    lines += [
        "",
        f"  선언 {declared} · 실측 {measured} · 기본값 {default}",
        "",
        "  해석: '기본값'은 근거 없이 고른 값입니다. 틀렸으면 "
        f"{CONFIG_NAME} 에 그 키만 적어 덮으십시오.",
        bar,
    ]
    return "\n".join(lines)


# ── 판정 경로에서 쓰는 설정 조회 ──────────────────────────────────────────────
#
# 검수(detect)는 여기서 하지 않는다. 자동 추론은 `cli init` / `cli inspect` 처럼
# 사람이 결과를 눈으로 확인하는 경로에서만 돌린다 — 판정 경로에서 조용히 추론하면
# 무엇을 근거로 거부·통과했는지 재현할 수 없다 (TS-009 가 정확히 그 문제였다).
#
# 설정 파일이 없으면 `ProjectConfig()` 의 기본값이 쓰이고, 그 기본값은 설정 외부화
# 이전의 하드코딩과 **같은 값**이다. 따라서 `.harness.json` 을 추가하지 않은
# 프로젝트의 동작은 변하지 않는다.

_CFG_CACHE: dict[str, ProjectConfig] = {}


def config_for(project_root: str | Path, harness_root: str | Path | None = None
               ) -> ProjectConfig:
    """대상 경로에 적용할 설정. `project_root` 가 항상 `target` 을 이긴다.

    호출자(재현 스크립트의 임시 디렉터리 등)가 명시한 경로를 설정 파일이
    바꿔버리면 검증의 격리가 깨지므로, target 만은 인자가 우선한다.

    해석 순서 (TS-025):
      1. `<project_root>/.harness.json` — **프로젝트가 자기 규약을 선언한다**
      2. `<harness_root>/.harness.json` — 하네스의 기본 (이 레포의 배치:
         명세는 루트, 앱은 web_target/)
      3. `ProjectConfig()` 기본값

      1번이 없었던 것이 실측된 버그다. `harness_root` 를 `config.BASE_DIR` 로
      하드코딩해서, 외부 프로젝트를 `--project` 로 지정하면 **이 레포의 설정**이
      적용됐다 — `main_portfolio` 가 `.harness.json` 에 `runner: vitest` 를 선언했는데
      `runner=jest` 가 적용되고 런처가 None 이 되어, 게이트가 "jest 를 찾을 수 없다"로
      전부 거부했다. TS-017 은 `init`/`inspect` 만 시험했고 **게이트 경로는 외부
      프로젝트에 한 번도 돌려보지 않았다.**

      `web_target` 은 자기 `.harness.json` 이 없으므로 2번으로 떨어진다 —
      기존 동작은 변하지 않는다.
    """
    if harness_root is None:
        import config as _config
        harness_root = _config.BASE_DIR
    key = str(Path(project_root).resolve())
    cached = _CFG_CACHE.get(key)
    if cached is not None:
        return cached
    # 프로젝트 자신의 선언이 하네스의 기본을 이긴다
    own = Path(key) / CONFIG_NAME
    source = key if own.is_file() else harness_root
    cfg, _ = load(source, detect_if_missing=False)
    cfg.target = key
    _CFG_CACHE[key] = cfg
    return cfg


def clear_cache() -> None:
    """테스트에서 설정을 바꿔 끼울 때 쓴다."""
    _CFG_CACHE.clear()

"""
harness/runner.py
─────────────────
**테스트 런너 추상화 — 생태계에 묶인 전부.**

측정 결과 (2,120줄 중):
  `cli.py`·`metrics.py`·`tags.py` 는 0% 가 런너에 묶여 있었고, `verify.py` 만 33%,
  `mutate.py` 가 8.6% 였다. 즉 하네스의 판정 **정책**은 처음부터 생태계 중립이었고
  `subprocess` 호출 네 군데만 jest 전용이었다.

  이 모듈이 그 네 군데다. 다른 생태계를 붙이려면 **이 파일에만** 클래스를 추가한다.

네 가지 연산 (이 이상은 런너에게 묻지 않는다):
  1. `run_all()`       — 전체 스위트를 돌린다. 사람이 읽을 출력.
  2. `results()`        — 구조화된 결과. 테스트 **개별 이름과 상태**가 필요하다
                          (증거 게이트가 기능 ID 를 인용하는 테스트를 찾는다).
  3. `coverage()`       — 주어진 테스트 파일/이름만 돌려 **소스별 실행 statement 수**.
  4. `typechecks()`     — 코드가 정적으로 유효한가 (돌연변이 유효성 확인).

설계 원칙 — 실패를 성공으로 오해하지 않는다:
  모든 연산은 `(값, 진단)` 을 돌려주고 값이 `None` 이면 **측정 실패**다.
  측정 실패는 '통과'가 아니다 (TS-016). 게이트는 None 을 거부로 처리한다.

Windows 함정 (TS-006, 재발 방지):
  `subprocess.run(["npx", ...])` 는 shell=False 에서 `npx.cmd` 를 찾지 못한다.
  `shutil.which` 로 PATHEXT 를 처리하고, 프로젝트 로컬 바이너리를 **절대 경로로**
  우선한다 — cwd 가 전환되므로 상대 경로는 깨진다.

vitest 함정:
  `vitest` 를 인자 없이 부르면 **watch 모드로 멈춘다.** 반드시 `run` 서브커맨드를
  붙인다. 이것 하나로 CI 가 타임아웃까지 매달린다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from harness.project import ProjectConfig


@dataclass
class Results:
    """런너 중립 테스트 결과. 모든 런너가 이 모양으로 정규화한다."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    suites_total: int = 0
    suites_failed: int = 0
    #: (전체이름, 상태) — 상태는 'passed' | 'failed' | 'skipped' | 'unknown'
    assertions: list[tuple[str, str]] = field(default_factory=list)

    def green(self) -> bool:
        return self.failed == 0 and self.suites_failed == 0 and self.total > 0


@dataclass
class Coverage:
    """소스 파일별 실행된 statement 수 + **실행된 줄 번호**. 테스트 파일은 제외한다.

    `executed_lines` 가 왜 필요한가 (TS-026):
      `per_file` 은 개수뿐이라 "이 파일이 17줄 실행됐다"까지만 안다. 돌연변이는
      **줄 단위로** 결함을 심으므로, 개수만으로 파일을 고르면 그 파일의 미실행
      줄에 변이가 들어간다. 미실행 줄의 변이는 어떤 테스트도 지나가지 않으므로
      **반드시 생존**하고, 그 생존이 점수의 분모에 들어가 점수를 낮춘다.

      실측: `LoginForm.tsx` 의 변이 후보 18곳 중 **실행되는 것은 2곳**이었다.
      나머지 16곳은 넣기만 하면 생존이 보장된 자리였다.

    비어 있으면 "줄 지도를 얻지 못했다"는 뜻이다 — **"실행된 줄이 없다"가 아니다.**
    호출자가 그 둘을 구분해야 한다 (측정 실패는 통과가 아니다 — TS-016).
    """

    per_file: dict[str, int] = field(default_factory=dict)
    executed_lines: dict[str, set[int]] = field(default_factory=dict)

    def total(self) -> int:
        return sum(self.per_file.values())

    def top(self, n: int = 5) -> list[str]:
        ranked = sorted(self.per_file.items(), key=lambda kv: -kv[1])
        return [f"{name} ({count})" for name, count in ranked[:n]]

    def lines_for(self, name: str) -> set[int] | None:
        """그 파일에서 실행된 줄 번호. 줄 지도가 없으면 `None`.

        `None` 과 `set()` 을 구분한다 — 전자는 '모른다', 후자는 '하나도 실행되지
        않았다'다. 전자를 후자로 취급하면 측정 실패가 조용히 '변이 대상 없음'이
        되고, 후자를 전자로 취급하면 미실행 파일에 변이를 넣는다.
        """
        return self.executed_lines.get(name)


class Runner:
    """런너 공통 계약. 하위 클래스는 네 연산만 구현한다."""

    name = "none"

    def __init__(self, target: Path, cfg: ProjectConfig) -> None:
        self.target = Path(target).resolve()
        self.cfg = cfg

    # ── 하위 클래스가 구현 ──────────────────────────────────────────────────

    def launcher(self) -> list[str] | None:
        """실행 커맨드 접두사. None 이면 런너를 실행할 수 없다."""
        raise NotImplementedError

    def run_all(self, path: str = ".", coverage: bool = False) -> tuple[int | None, str]:
        raise NotImplementedError

    def results(self) -> tuple[Results | None, str]:
        raise NotImplementedError

    def coverage(self, test_files: list[str], name_pattern: str) -> tuple[Coverage | None, str]:
        raise NotImplementedError

    def run_scoped(self, test_files: list[str], name_pattern: str) -> tuple[int | None, str]:
        """주어진 파일/이름만 돌린다. 돌연변이가 '테스트가 실패하는가'를 묻는 데 쓴다.

        커버리지 없이 돌린다 — 변이당 수십 번 반복되므로 측정을 끼우면 분 단위가 된다.
        """
        raise NotImplementedError

    # ── 공통 ────────────────────────────────────────────────────────────────

    def available(self) -> tuple[bool, str]:
        if self.launcher() is None:
            return False, (
                f"[오류] {self.name} 실행 파일을 찾을 수 없습니다. "
                f"{self.target} 에서 의존성을 먼저 설치하십시오."
            )
        return True, ""

    def typechecks(self) -> tuple[bool, str]:
        """정적 검사 통과 여부. 커맨드가 선언되지 않았으면 (True, 사유) — 건너뛴다.

        건너뛸 때 True 를 돌려주는 이유: 돌연변이에서 '확인 불가'를 '무효'로 처리하면
        모든 변이가 폐기되어 점수가 사라진다. 대신 사유를 함께 돌려 보고서가
        **과대평가 가능성을 명시**하게 한다.
        """
        if not self.cfg.typecheck:
            return True, "정적 검사 커맨드가 선언되지 않아 건너뜀"
        cmd = list(self.cfg.typecheck)
        exe = shutil.which(cmd[0])
        if exe is None:
            return True, f"{cmd[0]} 을 찾을 수 없어 건너뜀"
        code, _ = self._run([exe, *cmd[1:]], timeout=180)
        return code == 0, ""

    def _run(self, cmd: list[str], timeout: int | None = None) -> tuple[int | None, str]:
        timeout = timeout or config.TOOL_TIMEOUTS.get("run_tests", 120)
        try:
            r = subprocess.run(
                cmd, cwd=str(self.target), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
            return r.returncode, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return None, f"[오류] 타임아웃 ({timeout}초): {' '.join(cmd[:3])}"
        except FileNotFoundError:
            return None, f"[오류] 실행 파일을 찾을 수 없습니다: {cmd[0]}"

    def _local_bin(self, *names: str) -> list[str] | None:
        """node_modules/.bin 의 바이너리를 절대 경로로 찾는다 (Windows PATHEXT 포함)."""
        bin_dir = self.target / "node_modules" / ".bin"
        for base in names:
            for suffix in (".cmd", ".CMD", ".ps1", ""):
                candidate = bin_dir / f"{base}{suffix}"
                if candidate.is_file() and suffix != ".ps1":
                    return [str(candidate)]
        return None

    def _is_source(self, name: str) -> bool:
        """커버리지 집계에서 **테스트 파일 자신**을 제외한다 — 증거가 아니다."""
        return not self.cfg.is_test_file(name)


# ── JS 공통 ──────────────────────────────────────────────────────────────────

class _JsRunner(Runner):
    """jest·vitest 공통. 둘의 차이는 플래그 이름뿐이다."""

    config_names: tuple[str, ...] = ()
    dep_name = ""

    # 플래그 방언
    root_flag = "--rootDir"
    json_flags: tuple[str, ...] = ("--json",)
    no_coverage_flags: tuple[str, ...] = ("--no-coverage",)
    pre_args: tuple[str, ...] = ()           # vitest 의 'run'

    def _coverage_flags(self, out_dir: str) -> list[str]:
        raise NotImplementedError

    def launcher(self) -> list[str] | None:
        local = self._local_bin(self.name)
        if local:
            return [*local, *self.pre_args]
        # npx 폴백은 **대상이 실제로 이 런너를 설정했을 때만** (TS-006/TS-008).
        # 근거: 설정을 못 찾은 jest 는 상위로 올라가 rootDir 을 사용자 홈으로 잡고
        # .vscode/extensions 전체를 스캔하며 2분을 태웠다 — 실측.
        if not self._has_config():
            return None
        npx = shutil.which("npx")
        if npx:
            return [npx, "--no-install", self.name, *self.pre_args]
        return None

    def _has_config(self) -> bool:
        for name in self.config_names:
            if (self.target / name).is_file():
                return True
        pkg = self.target / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
            if isinstance(data, dict) and self.dep_name in data:
                return True
        return False

    def _root_args(self) -> list[str]:
        return [self.root_flag, str(self.target)]

    def available(self) -> tuple[bool, str]:
        """**실제로 돌 수 있는가** — launcher 가 있다는 것만으로는 부족하다.

        `launcher()` 의 npx 폴백은 설정 파일만 보고 커맨드를 만든다. 그런데 패키지가
        설치되지 않았으면 `npx --no-install` 은 런타임에 실패한다. 그 경우까지
        '실행 가능'으로 보고하면 준비 상태 보고가 거짓이 된다 — 실측으로 확인했다
        (vitest 미설치 Vite 프로젝트가 '실행 가능'으로 나왔다).

        따라서 세 단계로 나눈다:
          로컬 바이너리 있음       → 확실히 가능
          의존성에 선언됨(미설치)  → 가능하나 `npm install` 필요
          둘 다 아님               → 불가능
        """
        if self._local_bin(self.name):
            return True, ""
        pkg = self.target / "package.json"
        declared = False
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                deps = {**(data.get("dependencies") or {}),
                        **(data.get("devDependencies") or {})}
                declared = self.dep_name in deps
            except (json.JSONDecodeError, OSError):
                declared = False
        if declared:
            return False, (
                f"[오류] {self.name} 가 package.json 에 선언되어 있지만 설치되지 "
                f"않았습니다. {self.target} 에서 `npm install` 을 실행하십시오."
            )
        return False, (
            f"[오류] {self.name} 가 설치되어 있지 않고 의존성에도 선언되지 않았습니다. "
            f"`npm install -D {self.name}` 로 추가하십시오."
        )

    def run_all(self, path: str = ".", coverage: bool = False) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        if coverage:
            tmp = tempfile.mkdtemp(prefix="harness-cov-")
            try:
                return self._run([*launcher, path, *self._root_args(),
                                  *self._coverage_flags(tmp)])
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return self._run([*launcher, path, *self._root_args(), *self.no_coverage_flags])

    def run_scoped(self, test_files: list[str], name_pattern: str) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        return self._run([
            *launcher, *test_files, *self._root_args(),
            "--testNamePattern", name_pattern, *self.no_coverage_flags,
        ])

    def results(self) -> tuple[Results | None, str]:
        """`--json` 으로 돌려 개별 테스트 이름과 상태를 얻는다.

        테스트가 실패해도 런너는 JSON 을 쓴다(종료 코드만 1). 따라서 종료 코드와
        무관하게 파일을 읽는다 — 실패 내역 자체가 판정에 필요한 증거다.
        결과는 임시 디렉터리에 쓴다 (대상 레포를 오염시키지 않는다).
        """
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]

        tmp_dir = tempfile.mkdtemp(prefix=f"harness-{self.name}-")
        out_path = Path(tmp_dir) / "results.json"
        try:
            code, output = self._run([
                *launcher, ".", *self._root_args(), *self.no_coverage_flags,
                *self.json_flags, f"--outputFile={out_path}",
            ])
            if code is None:
                return None, output
            if not out_path.is_file():
                return None, (f"[오류] {self.name} 가 결과 JSON 을 생성하지 않았습니다.\n"
                              + output[-800:])
            try:
                raw = json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return None, f"[오류] {self.name} 결과 JSON 파싱 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return self._normalize(raw), ""

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> Results:
        """jest 형식 JSON → Results. vitest 의 json 리포터도 같은 모양이다."""
        assertions: list[tuple[str, str]] = []
        for suite in raw.get("testResults", []) or []:
            for a in suite.get("assertionResults", []) or []:
                full = a.get("fullName")
                if not full:
                    ancestors = a.get("ancestorTitles") or []
                    full = " ".join([*ancestors, a.get("title", "")]).strip()
                assertions.append((full, a.get("status", "unknown")))
        return Results(
            total=int(raw.get("numTotalTests", 0)),
            passed=int(raw.get("numPassedTests", 0)),
            failed=int(raw.get("numFailedTests", 0)),
            suites_total=int(raw.get("numTotalTestSuites", 0)),
            suites_failed=int(raw.get("numFailedTestSuites", 0)),
            assertions=assertions,
        )

    def coverage(self, test_files: list[str], name_pattern: str) -> tuple[Coverage | None, str]:
        """주어진 테스트 파일만 돌려 소스별 실행 statement 를 센다.

        **파일 범위까지 제한해야 한다** (TS-016). `--testNamePattern` 은 테스트
        *실행*만 건너뛰고 테스트 파일은 전부 import 한다. 그래서 다른 파일들의
        모듈 수준 import 가 섞여, 아무것도 실행하지 않는 공허한 테스트가
        42 statements 를 덮은 것으로 집계됐다 — 실측.

        부분 실행이므로 **커버리지 임계를 끈다.** 끄지 않으면 임계 미달로 비정상
        종료해 측정 실패와 구분되지 않는다 (TS-012 와 같은 혼동).
        """
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        if not test_files:
            return None, "[오류] 태그가 있는 단위 테스트 파일이 없습니다."

        tmp_dir = tempfile.mkdtemp(prefix="harness-cov-")
        try:
            code, output = self._run([
                *launcher, *test_files, *self._root_args(),
                "--testNamePattern", name_pattern,
                *self._coverage_flags(tmp_dir),
            ])
            summary = Path(tmp_dir) / "coverage-summary.json"
            if not summary.is_file():
                return None, ("[오류] 커버리지 요약이 생성되지 않았습니다.\n"
                              + (output or "")[-800:])
            data = json.loads(summary.read_text(encoding="utf-8"))
            # 줄 지도는 **별도 리포터**가 쓴다. 없으면 빈 지도로 둔다 —
            # 요약이 나왔는데 지도가 없는 것은 측정 실패가 아니다.
            final = Path(tmp_dir) / "coverage-final.json"
            line_map = self._executed_lines(final) if final.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"[오류] 커버리지 측정 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        per_file: dict[str, int] = {}
        for path, metrics in data.items():
            if path == "total" or not isinstance(metrics, dict):
                continue
            covered = int(metrics.get("statements", {}).get("covered", 0))
            if covered <= 0:
                continue
            name = Path(path).name
            if not self._is_source(name):
                continue
            per_file[name] = per_file.get(name, 0) + covered
        return Coverage(per_file, line_map), ""

    def _executed_lines(self, final: Path) -> dict[str, set[int]]:
        """istanbul `coverage-final.json` → 파일명별 실행된 줄 번호 (TS-026).

        **statement 의 시작 줄만 센다.** `start`~`end` 범위를 쓰면 안 된다 — 실측:
        `LoginForm.tsx` 에서 범위를 쓰면 167줄이 '실행됨'이 되고 미실행 statement
        54개 중 **48개가 그 안에 먹힌다.** 함수 선언 statement 는 모듈 로드 때
        실행되면서 호출되지 않은 본문 전체를 범위에 담기 때문이다. 그러면 지금
        고치려는 결함이 그대로 남는다.

        같은 줄에 실행된 statement 와 미실행 statement 가 함께 있으면 **제외**한다
        (`hit - miss`). 그 줄을 지나간 경로가 변이 지점을 지났다고 보장할 수 없다.
        실측에서 이 차이로 줄어드는 변이 후보는 `web_target` 기준 **0개**였다 —
        비용 없이 보수적인 쪽을 고를 수 있었다.
        """
        out: dict[str, set[int]] = {}
        try:
            data = json.loads(final.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return out
        for path, entry in data.items():
            if not isinstance(entry, dict):
                continue
            smap, counts = entry.get("statementMap"), entry.get("s")
            if not isinstance(smap, dict) or not isinstance(counts, dict):
                continue
            hit: set[int] = set()
            miss: set[int] = set()
            for sid, loc in smap.items():
                try:
                    line = int(loc["start"]["line"])
                except (KeyError, TypeError, ValueError):
                    continue
                (hit if counts.get(sid, 0) else miss).add(line)
            name = Path(path).name
            if not self._is_source(name):
                continue
            out.setdefault(name, set()).update(hit - miss)
        return out


class JestRunner(_JsRunner):
    name = "jest"
    dep_name = "jest"
    config_names = ("jest.config.ts", "jest.config.js", "jest.config.mjs",
                    "jest.config.cjs", "jest.config.json")

    def _coverage_flags(self, out_dir: str) -> list[str]:
        return [
            "--coverage",
            "--coverageReporters=json-summary",
            # `json` 이 `coverage-final.json`(statementMap + s)을 쓴다 — 줄 지도의
            # 유일한 출처다. `json-summary` 는 개수만 준다 (TS-026).
            "--coverageReporters=json",
            f"--coverageDirectory={out_dir}",
            "--coverageThreshold={}",
        ]


class VitestRunner(_JsRunner):
    name = "vitest"
    dep_name = "vitest"
    config_names = ("vitest.config.ts", "vitest.config.js", "vitest.config.mts",
                    "vite.config.ts", "vite.config.js", "vite.config.mts")
    #: `run` 없이 부르면 watch 모드로 **영원히 멈춘다**. 반드시 붙인다.
    pre_args = ("run",)
    root_flag = "--root"
    json_flags = ("--reporter=json",)
    no_coverage_flags = ("--coverage.enabled=false",)

    def _coverage_flags(self, out_dir: str) -> list[str]:
        # vitest 는 중첩 키 방언을 쓴다. 임계는 0 으로 낮춰 사실상 끈다
        # (jest 의 `--coverageThreshold={}` 에 해당하는 플래그가 없다).
        return [
            "--coverage.enabled=true",
            "--coverage.reporter=json-summary",
            "--coverage.reporter=json",      # 줄 지도 (TS-026)
            f"--coverage.reportsDirectory={out_dir}",
            "--coverage.thresholds.lines=0",
            "--coverage.thresholds.functions=0",
            "--coverage.thresholds.branches=0",
            "--coverage.thresholds.statements=0",
        ]


# ── Python ───────────────────────────────────────────────────────────────────

class PytestRunner(Runner):
    """pytest. JSON 리포터 플러그인 없이 **내장 junit-xml** 로 결과를 얻는다.

    근거: `pytest-json-report` 는 서드파티다. 남의 레포에 설치를 요구하지 않으려면
    내장 기능만 써야 한다. junit-xml 은 pytest 코어에 있고 stdlib 로 파싱된다.

    한계 — 커버리지는 `pytest-cov` 가 필요하다. 없으면 측정 실패를 반환하고,
    게이트는 그것을 **거부**로 처리한다 (측정 못 한 것을 통과시키지 않는다).
    진단 메시지가 설치 방법을 알려준다.
    """

    name = "pytest"

    def launcher(self) -> list[str] | None:
        for candidate in ("pytest", "py.test"):
            exe = shutil.which(candidate)
            if exe:
                return [exe]
        python = shutil.which("python") or shutil.which("python3")
        if python:
            return [python, "-m", "pytest"]
        return None

    def run_all(self, path: str = ".", coverage: bool = False) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        args = [*launcher, path, "-q"]
        if coverage:
            args += [f"--cov={d}" for d in self.cfg.source_dirs] + ["--cov-report=term"]
        return self._run(args)

    def results(self) -> tuple[Results | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        tmp_dir = tempfile.mkdtemp(prefix="harness-pytest-")
        xml_path = Path(tmp_dir) / "results.xml"
        try:
            code, output = self._run([*launcher, ".", "-q", f"--junit-xml={xml_path}"])
            if code is None:
                return None, output
            if not xml_path.is_file():
                return None, "[오류] pytest 가 junit-xml 을 생성하지 않았습니다.\n" + output[-800:]
            tree = ET.parse(xml_path)
        except ET.ParseError as exc:
            return None, f"[오류] junit-xml 파싱 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        assertions: list[tuple[str, str]] = []
        suites = tree.getroot().iter("testsuite")
        suites_total = suites_failed = 0
        for suite in suites:
            suites_total += 1
            if int(suite.get("failures", 0) or 0) or int(suite.get("errors", 0) or 0):
                suites_failed += 1
            for case in suite.iter("testcase"):
                full = " ".join(filter(None, [case.get("classname", ""), case.get("name", "")]))
                if case.find("failure") is not None or case.find("error") is not None:
                    status = "failed"
                elif case.find("skipped") is not None:
                    status = "skipped"
                else:
                    status = "passed"
                assertions.append((full.strip(), status))
        failed = sum(1 for _, s in assertions if s == "failed")
        passed = sum(1 for _, s in assertions if s == "passed")
        return Results(
            total=len(assertions), passed=passed, failed=failed,
            suites_total=suites_total, suites_failed=suites_failed,
            assertions=assertions,
        ), ""

    def run_scoped(self, test_files: list[str], name_pattern: str) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        return self._run([*launcher, *test_files, "-q", "-k", name_pattern.split("(")[0]])

    def coverage(self, test_files: list[str], name_pattern: str) -> tuple[Coverage | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        if not test_files:
            return None, "[오류] 태그가 있는 테스트 파일이 없습니다."

        tmp_dir = tempfile.mkdtemp(prefix="harness-cov-")
        out = Path(tmp_dir) / "coverage.json"
        try:
            # `-k` 는 정규식이 아니라 부분 문자열 식이다. 기능 ID 는 그대로 쓸 수 있다.
            code, output = self._run([
                *launcher, *test_files, "-q", "-k", name_pattern.split("(")[0],
                *[f"--cov={d}" for d in self.cfg.source_dirs],
                f"--cov-report=json:{out}",
            ])
            if not out.is_file():
                hint = ""
                if "unrecognized arguments" in (output or "") or "--cov" in (output or ""):
                    hint = " pytest-cov 가 설치되지 않은 것 같습니다 (pip install pytest-cov)."
                return None, f"[오류] 커버리지 JSON 이 생성되지 않았습니다.{hint}"
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"[오류] 커버리지 측정 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return self._parse_coverage(data), ""

    def _parse_coverage(self, data: dict[str, Any]) -> Coverage:
        """pytest-cov JSON → `Coverage`. **파싱만** 한다 (서브프로세스 없음).

        런너 실행과 분리하는 이유: pytest 는 이 레포에 설치되어 있지 않고
        CI 에도 없다. 파싱을 메서드로 떼어 두면 **pytest 없이 파싱 규약을 검증**할
        수 있다 — TS-025 가 "pytest 실행 경로는 미검증"으로 기록한 공백을 전부
        메우지는 못하지만, 그중 파싱 부분은 메운다.

        pytest-cov 는 줄 번호를 `executed_lines` 로 **직접** 준다. istanbul 처럼
        statement 를 줄로 환산할 필요가 없다 (TS-026).
        """
        per_file: dict[str, int] = {}
        line_map: dict[str, set[int]] = {}
        for path, entry in (data.get("files") or {}).items():
            if not isinstance(entry, dict):
                continue
            covered = int((entry.get("summary") or {}).get("covered_lines", 0))
            if covered <= 0:
                continue
            name = Path(path).name
            if not self._is_source(name):
                continue
            per_file[name] = per_file.get(name, 0) + covered
            executed = entry.get("executed_lines")
            if isinstance(executed, list):
                line_map.setdefault(name, set()).update(
                    int(n) for n in executed if isinstance(n, int)
                )
        return Coverage(per_file, line_map)


# ── 선택 ─────────────────────────────────────────────────────────────────────

RUNNERS: dict[str, type[Runner]] = {
    "jest": JestRunner,
    "vitest": VitestRunner,
    "pytest": PytestRunner,
}


def for_project(cfg: ProjectConfig, harness_root: str | Path) -> Runner:
    """설정에 선언된 런너 인스턴스. 모르는 이름이면 예외 — 조용히 넘기지 않는다."""
    cls = RUNNERS.get(cfg.runner)
    if cls is None:
        raise ValueError(
            f"알 수 없는 런너 {cfg.runner!r}. 지원: {', '.join(sorted(RUNNERS))}. "
            f"새 생태계를 붙이려면 harness/runner.py 에 Runner 하위 클래스를 추가하십시오 "
            f"(네 연산만 구현하면 됩니다)."
        )
    return cls(cfg.target_path(harness_root), cfg)

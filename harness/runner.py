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
import sys
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


# ── Python stdlib ────────────────────────────────────────────────────────────

#: `unittest` 결과를 JSON 으로 받는 수집기. 임시 파일로 써서 실행한다.
#:
#: **왜 `-v` 출력을 파싱하지 않는가 — 실측 (TS-031):**
#:
#:   docstring 이 있으면 unittest 는 **두 줄로** 쪼개고 상태를 둘째 줄에 붙인다.
#:     test_ut01_1_x (tests.test_conv.ConvertTest)
#:     UT-01.1: 선언된 통화는 전부 변환된다 ... ok
#:   docstring 이 없으면 한 줄이다.
#:     test_ut02_1_y (tests.test_conv.Demo) ... skipped '일부러'
#:
#:   즉 파싱 규칙이 **docstring 유무에 따라 달라진다.** 정규식으로 다루면
#:   TS-021 의 함정(출력 형식을 시험하는 코드)에 그대로 들어간다.
#:
#: stdlib 에 JSON 리포터가 없을 때의 올바른 답은 **그 생태계의 API 를 쓰는 것**이다.
#: `unittest.TextTestResult` 를 상속해 수집하면 형식에 의존하지 않는다 — jest 의
#: `--json` 과 같은 수준의 구조화된 결과다.
#:
#: 테스트 이름은 `shortDescription()`(docstring 첫 줄)을 쓴다. 파이썬 식별자에는
#: 하이픈을 쓸 수 없어 함수 이름에 `UT-01` 이 들어가지 않기 때문이다 — pytest 와
#: 같은 이유다. docstring 이 없으면 점 표기 id 로 떨어지고, 그 이름에는 기능 ID 가
#: 없으므로 **증거로 계수되지 않는다.** 그것이 맞는 동작이다 (태그 없는 테스트).
_UNITTEST_COLLECTOR = '''
import json, os, re, sys, unittest


class _JsonResult(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []

    def _label(self, test):
        return test.shortDescription() or test.id()

    def addSuccess(self, t):
        super().addSuccess(t); self.rows.append([self._label(t), "passed"])

    def addFailure(self, t, e):
        super().addFailure(t, e); self.rows.append([self._label(t), "failed"])

    def addError(self, t, e):
        super().addError(t, e); self.rows.append([self._label(t), "failed"])

    def addSkip(self, t, r):
        super().addSkip(t, r); self.rows.append([self._label(t), "skipped"])

    def addExpectedFailure(self, t, e):
        super().addExpectedFailure(t, e); self.rows.append([self._label(t), "skipped"])

    def addUnexpectedSuccess(self, t):
        super().addUnexpectedSuccess(t); self.rows.append([self._label(t), "failed"])


def _label_of(test):
    return test.shortDescription() or test.id()


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


# **cwd 를 sys.path 에 넣는다** (TS-031). 이 수집기는 임시 디렉터리에 쓰여 실행되므로
# `python <script>` 는 **스크립트의 디렉터리**를 sys.path[0] 에 넣는다 — 대상 프로젝트가
# 아니다. 그래서 `loadTestsFromNames(["tests.test_wallet"])` 가 import 에 실패하고
# unittest 는 `_FailedTest` 를 만든다. 그 가짜 테스트의 이름에는 기능 ID 가 없으므로
# 패턴 필터가 전부 걸러내고, 남은 커버리지는 **모듈 import 뿐**이 된다.
# `discover` 는 `top_level_dir` 을 sys.path 에 넣어 주므로 그 경로만 우연히 동작했다.
sys.path.insert(0, os.getcwd())

out_path = sys.argv[1]
start = sys.argv[2]
pattern = sys.argv[3] if len(sys.argv) > 3 else ""
modules = sys.argv[4:]

loader = unittest.TestLoader()
if modules:
    suite = loader.loadTestsFromNames(modules)
else:
    suite = loader.discover(start, top_level_dir=".")

# **`loader.testNamePatterns` 를 쓰지 않는다** (TS-031).
#
# 그것은 **메서드 이름**에 매칭된다. 파이썬 식별자에는 하이픈을 쓸 수 없으므로
# `def test_UT-01_...` 이 불가능하고, 하네스가 보는 테스트 이름은 docstring 이다.
# 그래서 `testNamePatterns = ["*UT-01*"]` 는 **모든 테스트를 걸러냈고**, 남은 것은
# 모듈 import 뿐이라 커버리지 4줄이 나왔다 — 그 4줄이 '증거'로 계수되어 게이트가
# 통과했다. TS-016 이 막은 '아무것도 실행하지 않는 증거'가 새 런너에서 되살아난 것이다.
#
# 필터는 **하네스가 쓰는 이름(라벨)** 기준이어야 한다. 그 정의가 이 수집기 안에
# 있으므로 여기서 거른다.
selected = -1
if pattern:
    # `name_pattern` 은 **정규식**이다 — jest 의 `--testNamePattern` 방언을 따른다.
    # `feature_name_pattern("UT-01")` 은 `UT\-01(?![0-9])` 를 돌려준다. 문자열
    # 포함으로 비교하면 절대 맞지 않고, 그 결과 테스트 0개가 선택되어
    # **모듈 import 만의 커버리지가 증거로 계수된다** (TS-031 에서 실측).
    rx = re.compile(pattern)
    picked = [t for t in _flatten(suite) if rx.search(_label_of(t))]
    selected = len(picked)
    suite = unittest.TestSuite(picked)

sink = open(os.devnull, "w", encoding="utf-8")
res = unittest.TextTestRunner(resultclass=_JsonResult, verbosity=0, stream=sink).run(suite)
sink.close()
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump({"total": res.testsRun, "rows": res.rows,
               "selected": selected,
               "failed": len(res.failures) + len(res.errors)}, fh, ensure_ascii=False)

# 패턴이 **하나도 못 맞췄으면 측정 실패**다 (TS-016·TS-031). 빈 스위트는
# `wasSuccessful()` 이 True 이므로 그대로 두면 "테스트가 전부 통과했다"로 읽힌다.
# 돌연변이에서는 그것이 '변이를 잡지 못했다'(생존)로 계수되어 점수를 왜곡한다.
# 종료 코드 3 으로 구분해 호출자가 '실패'와 '대상 없음'을 가릴 수 있게 한다.
if selected == 0:
    sys.exit(3)
sys.exit(0 if res.wasSuccessful() else 1)
'''


class UnittestRunner(PytestRunner):
    """파이썬 **표준 라이브러리** `unittest`. 설치가 필요 없다 (TS-031).

    `PytestRunner` 를 상속하는 이유는 하나다 — 커버리지 JSON 파싱(`_parse_coverage`)이
    **완전히 같다.** `coverage.py` 와 `pytest-cov` 가 같은 모양을 내기 때문이다
    (실측: `files: {path: {executed_lines, missing_lines, summary}}`). 그 외는 전부
    재정의한다.

    이 런너가 중요한 이유: **설치 0으로 런너 실행 계층을 CI 에서 돌릴 수 있는 유일한
    파이썬 경로**다. TS-025·TS-030 이 "jest 만 실행 계층이 CI 에 있다"를 공백으로
    기록했고, 이것이 그 공백을 메운다.

    커버리지는 `coverage` 패키지가 필요하다 — 대상 프로젝트의 도구이지 하네스의
    의존성이 아니다(pytest-cov 와 같은 위치). 없으면 측정 실패를 반환하고 게이트가
    **거부**한다. 진단이 설치 방법을 알려준다.
    """

    name = "unittest"

    #: 테스트를 찾을 시작 디렉터리 후보. 선언된 것이 없으면 순서대로 시도한다.
    _discover_dirs = ("tests", "test", ".")

    def launcher(self) -> list[str] | None:
        """stdlib 이므로 **파이썬만 있으면 된다.**

        다른 런너와 달리 '선언됐으나 미설치' 상태가 존재하지 않는다 —
        `docs/adding-a-language.md` 의 예시가 그 경우를 다루지 않았다 (TS-031).
        """
        python = shutil.which("python") or shutil.which("python3") or sys.executable
        return [python, "-m", "unittest"] if python else None

    def available(self) -> tuple[bool, str]:
        if self.launcher() is None:
            return False, "[오류] 파이썬 실행 파일을 찾을 수 없습니다."
        return True, ""

    # ── 경로 ↔ 모듈 이름 ────────────────────────────────────────────────────

    def _start_dir(self) -> str:
        """테스트를 찾을 디렉터리. 없는 것을 넘기면 discover 가 바로 실패한다."""
        for d in self._discover_dirs:
            if (self.target / d).is_dir():
                return d
        return "."

    def _module_of(self, test_file: str) -> str:
        """`tests/test_conv.py` → `tests.test_conv`.

        `unittest` 는 **점 표기 모듈 이름**만 받는다 (파일 경로를 받지 않는다).
        `docs/adding-a-language.md` 가 이 변환을 언급하지 않았다 (TS-031).

        범위를 파일로 제한하는 것은 선택이 아니다 — 이름 패턴만 쓰면 다른 테스트
        파일도 전부 import 되어 모듈 수준 코드가 커버리지에 섞인다 (TS-016 의 함정 2).
        """
        rel = test_file.replace("\\", "/")
        if rel.endswith(".py"):
            rel = rel[:-3]
        return rel.strip("/").replace("/", ".")

    # ── 네 가지 연산 ────────────────────────────────────────────────────────

    def run_all(self, path: str = ".", coverage: bool = False) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        start = self._start_dir() if path in (".", "") else path
        args = [*launcher, "discover", "-s", start, "-t", "."]
        if not coverage:
            return self._run(args)
        cov = self._coverage_cmd()
        if cov is None:
            return None, self._coverage_missing()
        return self._run([*cov, "run", *self._source_args(), "-m", "unittest",
                          "discover", "-s", start, "-t", "."])

    def results(self) -> tuple[Results | None, str]:
        """수집기를 임시 파일로 써서 실행하고 JSON 을 읽는다.

        테스트가 실패해도 JSON 을 쓴다(종료 코드만 1) — 실패 내역 자체가 판정에
        필요한 증거이므로 종료 코드와 무관하게 파일을 읽는다 (jest 경로와 같다).
        """
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        python = launcher[0]

        tmp_dir = tempfile.mkdtemp(prefix="harness-unittest-")
        script = Path(tmp_dir) / "collect.py"
        out_path = Path(tmp_dir) / "results.json"
        try:
            script.write_text(_UNITTEST_COLLECTOR, encoding="utf-8")
            code, output = self._run([python, str(script), str(out_path),
                                      self._start_dir(), ""])
            if not out_path.is_file():
                return None, ("[오류] unittest 결과 JSON 이 생성되지 않았습니다.\n"
                              + (output or "")[-800:])
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"[오류] unittest 결과 수집 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        rows = [(str(n), str(s)) for n, s in (data.get("rows") or [])]
        total = int(data.get("total", 0))
        failed = int(data.get("failed", 0))
        return Results(
            total=total,
            passed=sum(1 for _n, s in rows if s == "passed"),
            failed=failed,
            # unittest 는 '스위트' 개념을 노출하지 않는다. 파일 단위로 센다 —
            # 없는 수치를 만들어내지 않고, 실패가 있으면 1 로 둔다.
            suites_total=1,
            suites_failed=1 if failed else 0,
            assertions=rows,
        ), ""

    def coverage(self, test_files: list[str], name_pattern: str
                 ) -> tuple[Coverage | None, str]:
        """주어진 테스트 **파일과 이름**으로 범위를 좁혀 커버리지를 측정한다.

        파일까지 좁히는 이유는 TS-016 의 함정 2 — 이름 패턴만 쓰면 다른 테스트
        파일이 전부 import 되어 모듈 수준 코드가 커버리지에 섞인다.
        """
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        if not test_files:
            return None, "[오류] 태그가 있는 테스트 파일이 없습니다."
        cov = self._coverage_cmd()
        if cov is None:
            return None, self._coverage_missing()

        modules = [self._module_of(f) for f in test_files]
        tmp_dir = tempfile.mkdtemp(prefix="harness-unittest-cov-")
        script = Path(tmp_dir) / "collect.py"
        out_json = Path(tmp_dir) / "cov.json"
        data_file = Path(tmp_dir) / ".coverage"
        try:
            script.write_text(_UNITTEST_COLLECTOR, encoding="utf-8")
            env_args = ["--data-file", str(data_file)]
            self._run([*cov, "run", *env_args, *self._source_args(), str(script),
                       str(Path(tmp_dir) / "res.json"), self._start_dir(),
                       name_pattern, *modules])
            code, output = self._run([*cov, "json", *env_args, "-o", str(out_json)])
            if not out_json.is_file():
                return None, ("[오류] 커버리지 JSON 이 생성되지 않았습니다.\n"
                              + (output or "")[-600:])
            data = json.loads(out_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"[오류] 커버리지 측정 실패: {exc}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # 파싱은 pytest 와 **완전히 같다** — coverage.py 와 pytest-cov 가 같은 모양을 낸다
        return self._parse_coverage(data), ""

    def run_scoped(self, test_files: list[str], name_pattern: str
                   ) -> tuple[int | None, str]:
        launcher = self.launcher()
        if launcher is None:
            return None, self.available()[1]
        python = launcher[0]
        modules = [self._module_of(f) for f in test_files]
        tmp_dir = tempfile.mkdtemp(prefix="harness-unittest-scoped-")
        script = Path(tmp_dir) / "collect.py"
        try:
            script.write_text(_UNITTEST_COLLECTOR, encoding="utf-8")
            code, output = self._run([python, str(script),
                                      str(Path(tmp_dir) / "r.json"),
                                      self._start_dir(), name_pattern, *modules])
            if code == 3:
                # 패턴이 하나도 못 맞췄다 — **측정 실패**이지 '통과'가 아니다.
                # None 을 돌려주면 돌연변이가 '잡지 못했다'(생존)로 센다. 과소평가는
                # 안전한 방향이다 — 점수를 좋게 보이게 만들지 않는다 (TS-026 의 규칙).
                return None, (f"[오류] 이름 패턴 {name_pattern!r} 에 맞는 테스트가 "
                              f"없습니다 (모듈: {', '.join(modules)}). "
                              "측정 실패는 통과가 아닙니다.")
            return code, output
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── coverage 패키지 ─────────────────────────────────────────────────────

    def _coverage_cmd(self) -> list[str] | None:
        python = shutil.which("python") or shutil.which("python3") or sys.executable
        if not python:
            return None
        code, _ = self._run([python, "-m", "coverage", "--version"], timeout=30)
        return [python, "-m", "coverage"] if code == 0 else None

    def _coverage_missing(self) -> str:
        return ("[오류] `coverage` 패키지가 없어 커버리지를 측정할 수 없습니다. "
                "`pip install coverage` 로 설치하십시오. 측정 실패는 통과가 "
                "아니므로 게이트가 거부합니다 (TS-016).")

    def _source_args(self) -> list[str]:
        dirs = [d for d in self.cfg.source_dirs if (self.target / d).is_dir()]
        return [f"--source={','.join(dirs)}"] if dirs else []


# ── 선택 ─────────────────────────────────────────────────────────────────────

RUNNERS: dict[str, type[Runner]] = {
    "jest": JestRunner,
    "vitest": VitestRunner,
    "pytest": PytestRunner,
    "unittest": UnittestRunner,
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

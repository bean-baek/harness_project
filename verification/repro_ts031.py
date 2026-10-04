"""
TS-031 검증 스크립트 — 체크리스트를 따라가며 새 런너를 붙였다
──────────────────────────────────────────────────────────
`docs/adding-a-language.md` 는 "`Runner` 서브클래스 1개 + 픽스처 1개면 게이트가 돈다"고
주장했다. **그 주장은 검증되지 않은 것이었다** — TS-025 가 정확히 그런 주장이 두 번째
사례에서 깨진 기록이다. 그래서 절차를 실제로 따라가 `unittest` 런너를 붙였다.

왜 `unittest` 인가: **stdlib 이라 설치가 0** 이다. `coverage` 하나만 있으면 결과
파싱·범위 제한·커버리지 줄 지도까지 CI 에서 돌 수 있다 — TS-025·TS-030 이
"jest 만 런너 실행 계층이 CI 에 있다"로 기록한 공백을 메우는 유일한 파이썬 경로다.

**체크리스트를 따라가며 결함 7건이 나왔다.** 넷은 런너 구현의 함정이고 둘은 기존
검사기의 오탐이고 하나는 문서 자신의 오류다. 전부 음성 대조로 고정한다:

  ① `name_pattern` 이 **정규식**인데 문자열 포함으로 비교했다 → 테스트 0개 선택 →
     **모듈 import 만의 커버리지가 증거로 계수**되고 게이트가 통과했다 (TS-016 재발)
  ② 수집기를 임시 파일로 실행하면 `sys.path` 에 대상이 없다 → import 실패 →
     `_FailedTest` → 같은 결과
  ③ 패턴이 0개를 맞추면 빈 스위트가 `wasSuccessful()` True 다 → '통과'로 읽힌다
  ④ `unittest -v` 는 docstring 유무에 따라 **출력 줄 수가 달라진다** → 파싱 금지
  ⑤ `inspect._imported_stems` 가 JS 전용이었다 → 파이썬 import 를 못 봐 전부 오탐
  ⑥ `__init__.py` 를 stem(`__init__`)으로 찾아 패키지 import 를 놓쳤다
  ⑦ 지원 표가 런너→확장자 **하드코딩 딕셔너리**를 써서 새 런너의 계층을 전부 `—` 로
     보고했다 — 손으로 적은 표를 막으려고 만든 표 안에서 같은 실수를 했다

이 스크립트는 **실제로 런너를 돌린다** (설치 0). 다른 검증 스크립트는 전부 스텁이다.
`coverage` 가 없으면 커버리지 검사만 건너뛰고 그 사실을 출력한다.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import project as project_mod
from harness import runner as runner_mod
from harness import tags
from harness import inspect as inspect_mod
from harness.status import language_support
from harness.verify import (
    config_for,
    feature_name_pattern,
    load_features,
    runner_for,
    tagged_test_files,
)

FX = PROJECT / "verification" / "fixtures" / "unittest-app"

ok = 0
fail = 0
skipped = 0
NL = chr(10)


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


def note_skip(reason):
    global skipped
    skipped += 1
    print(f"  SKIP  {reason}")


print("\n[1] 런너가 등록되고 **설치 없이** 실행 가능한가")
check("RUNNERS 에 unittest 가 있다", "unittest" in runner_mod.RUNNERS, True)
project_mod.clear_cache()
cfg = config_for(str(FX))
check("픽스처가 unittest 를 선언한다", cfg.runner, "unittest")
r = runner_for(str(FX))
available, note = r.available()
# stdlib 이므로 '선언됐으나 미설치' 상태가 존재하지 않는다 — 문서의 예시가
# 그 경우를 다루지 않았다 (TS-031).
check("설치 없이 실행 가능하다 (stdlib)", available, True)
check("런처가 파이썬 -m unittest 다",
      r.launcher()[1:] if r.launcher() else [], ["-m", "unittest"])

print("\n[2] results() — docstring 을 테스트 이름으로 쓰는가")
# 파이썬 식별자에 하이픈을 쓸 수 없어 `def test_UT-01_...` 은 문법 오류다.
# 그래서 `shortDescription()`(docstring 첫 줄)이 이름이 된다 — pytest 와 같은 이유.
res, diag = r.results()
check("결과를 얻었다", res is not None, True)
if res:
    check("테스트 4개", res.total, 4)
    check("전부 통과", res.failed, 0)
    check("스위트가 녹색이다", res.green(), True)
    names = [n for n, _s in res.assertions]
    check("이름에 기능 ID 가 들어 있다",
          sum(1 for n in names if "UT-01" in n or "UT-02" in n), 4)
    check("메서드 이름이 아니라 docstring 이다",
          any(n.startswith("test_") for n in names), False)

print("\n[3] 태그 스캔이 파이썬 계열 규약을 쓰는가")
project_mod.clear_cache()
refs = tags.scan_tags(str(FX))
check("태그 6건 (스위트 2 + 단계 4)", len(refs), 6)
check("기능 ID 두 개", sorted({x.feature_id for x in refs}), ["UT-01", "UT-02"])
check("스위트 태그 2건", sum(1 for x in refs if x.is_suite), 2)
check("단계 태그 4건", sum(1 for x in refs if x.step), 4)
# `_suite_regex` 가 pytest 와 같은 분기를 쓴다 — 파이썬 계열에서는 **필수**다
check("unittest 는 class 기반 스위트 정규식을 쓴다",
      tags._suite_regex("unittest").pattern, tags._suite_regex("pytest").pattern)
check("JS 런너는 describe 정규식을 쓴다",
      "describe" in tags._suite_regex("jest").pattern, True)
project_mod.clear_cache()

print("\n[4] 수집기 — 정규식으로 거르는가 (음성 대조 포함)")
collector = runner_mod._UNITTEST_COLLECTOR
check("정규식을 쓴다 (문자열 포함이 아니다)", "re.compile(pattern)" in collector, True)
check("sys.path 에 cwd 를 넣는다", "sys.path.insert(0, os.getcwd())" in collector, True)
check("라벨은 shortDescription 우선", "shortDescription() or test.id()" in collector, True)
check("0개 선택이면 종료 코드 3", "sys.exit(3)" in collector, True)

# ── 음성 대조 ①: 문자열 포함으로 비교하면 하나도 못 맞춘다 ──────────────────
pat = feature_name_pattern("UT-01")
label = "UT-01.1: CURRENCIES 에 있는 통화는 모두 변환된다"
check("정규식은 라벨에 매칭된다", bool(re.search(pat, label)), True)
check("음성 대조: 문자열 포함으로는 매칭되지 않는다", pat in label, False)
check("그 패턴이 실제로 정규식 문법이다", pat, "UT" + chr(92) + "-01(?![0-9])")

# ── 음성 대조 ②: sys.path 없이 모듈을 로드하면 _FailedTest 가 된다 ──────────
tmp = Path(tempfile.mkdtemp(prefix="harness-ts031-"))
bad = collector.replace("sys.path.insert(0, os.getcwd())", "pass")
(tmp / "bad.py").write_text(bad, encoding="utf-8")
out = tmp / "bad.json"
subprocess.run([sys.executable, str(tmp / "bad.py"), str(out), "tests", "",
                "tests.test_wallet"], cwd=str(FX), capture_output=True)
rows = json.loads(out.read_text(encoding="utf-8"))["rows"] if out.is_file() else []
check("음성 대조: sys.path 없이는 import 가 실패한다",
      any("_FailedTest" in n for n, _s in rows), True)
check("그 가짜 테스트 이름에는 기능 ID 가 없다",
      any("UT-01" in n for n, _s in rows), False)

print("\n[5] 범위 제한 — 기능마다 다른 줄을 지나는가")
if r._coverage_cmd() is None:
    note_skip("`coverage` 패키지가 없어 커버리지 검사를 건너뜁니다 "
              "(pip install coverage). 측정 실패를 통과로 적지 않기 위해 "
              "건너뛴 사실을 출력합니다 — TS-016)")
else:
    project_mod.clear_cache()
    tf = tagged_test_files(str(FX), "UT-01")
    check("태그된 테스트 파일을 찾는다", tf, ["tests/test_wallet.py"])
    lines = {}
    for fid in ("UT-01", "UT-02"):
        cov, d = r.coverage(tf, feature_name_pattern(fid))
        check(f"{fid}: 커버리지를 얻었다", cov is not None, True)
        lines[fid] = sorted(cov.executed_lines.get("wallet.py", set())) if cov else []
    # 두 기능이 **다른 줄**을 지나야 한다. 같으면 범위 제한이 동작하지 않는 것이다.
    check("두 기능이 지나는 줄이 다르다", lines["UT-01"] != lines["UT-02"], True)
    src = (FX / "src" / "wallet.py").read_text(encoding="utf-8").split(NL)
    cur_line = next(i for i, l in enumerate(src, 1) if "unknown currency" in l)
    amt_line = next(i for i, l in enumerate(src, 1) if "must be positive" in l)
    check("UT-01 은 통화 거부 줄을 지난다", cur_line in lines["UT-01"], True)
    check("UT-01 은 금액 거부 줄을 지나지 않는다", amt_line in lines["UT-01"], False)
    check("UT-02 는 금액 거부 줄을 지난다", amt_line in lines["UT-02"], True)
    check("UT-02 는 통화 거부 줄을 지나지 않는다", cur_line in lines["UT-02"], False)

    # TS-026 — 호출되지 않는 함수의 본문은 실행된 줄에 없다
    never = next(i for i, l in enumerate(src, 1) if "flag is True" in l)
    check("never_reached 의 분기는 실행된 줄에 없다 (TS-026)",
          never in lines["UT-01"], False)

    # ── 음성 대조 ③: 없는 기능은 '통과'가 아니라 **측정 실패** ──────────────
    code, msg = r.run_scoped(tf, feature_name_pattern("UT-99"))
    check("패턴이 0개를 맞추면 None (측정 실패)", code, None)
    check("사유가 '측정 실패는 통과가 아니다' 를 말한다", "통과가 아닙니다" in msg, True)
    code_ok, _ = r.run_scoped(tf, feature_name_pattern("UT-01"))
    check("실제 기능은 0 (테스트 통과)", code_ok, 0)
    project_mod.clear_cache()

print("\n[6] 게이트가 끝까지 도는가 — 이것이 체크리스트의 주장이다")
if r._coverage_cmd() is None:
    note_skip("`coverage` 가 없어 게이트 종단 검사를 건너뜁니다")
else:
    env_args = [sys.executable, "-m", "harness.cli", "verify"]
    for fid in ("UT-01", "UT-02"):
        p = subprocess.run([*env_args, fid, "--project",
                            "verification/fixtures/unittest-app"],
                           cwd=str(PROJECT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env={**__import__("os").environ,
                                "PYTHONIOENCODING": "utf-8", "GOOGLE_API_KEY": ""})
        check(f"{fid}: 게이트 통과 (종료 코드 0)", p.returncode, 0)
        check(f"{fid}: 근거 테스트를 출력한다", "근거 테스트" in p.stdout, True)

print("\n[7] 기존 검사기의 파이썬 오탐이 고쳐졌는가")
# JS 는 모듈 경로를 따옴표로 싸지만 파이썬은 싸지 않는다. JS 정규식만 쓰면
# 파이썬 테스트가 소스를 import 해도 못 보고 `untested-source` 가 전부 오탐이 된다.
stems = inspect_mod._imported_stems("from src.wallet import CURRENCIES, convert\n")
check("파이썬 from-import 를 본다", "wallet" in stems, True)
check("패키지 이름도 담는다 (__init__.py 를 위해)", "src" in stems, True)
check("JS import 도 여전히 본다",
      "x" in inspect_mod._imported_stems("import { a } from './x';"), True)
check("음성 대조: 따옴표 정규식만으로는 파이썬을 못 본다",
      bool(inspect_mod._IMPORT_SPEC_RE.search("from src.wallet import X")), False)

project_mod.clear_cache()
rep = inspect_mod.inspect_project(FX)
untested = [c for c in rep.checks if c.kind == "untested-source"]
check("미테스트 소스 검사가 통과한다 (오탐 0)",
      untested[0].verdict if untested else "없음", "ok")
check("`__init__.py` 를 패키지 이름으로 찾는다 — 오탐이 아니다",
      "__init__" in (untested[0].detail if untested else ""), False)
project_mod.clear_cache()

print("\n[8] 지원 표가 새 런너를 **정직하게** 싣는가")
rows = language_support(PROJECT)
by = {x["runner"]: x for x in rows}
check("표에 unittest 가 있다", "unittest" in by, True)
check("피험체가 있다", by["unittest"]["subject"], "unittest-app")
check("게이트 O", by["unittest"]["gate"], True)
# ── 음성 대조 ⑦: 하드코딩 딕셔너리를 쓰면 새 런너의 계층이 전부 — 가 된다
check("검수 계층 O (하드코딩 매핑을 쓰지 않는다)", by["unittest"]["inspect"], True)
check("컬렉션 계층 O", by["unittest"]["collections"], True)
check("초안 계층은 — (.py 는 마크업이 아니다)", by["unittest"]["draft"], False)
check("줄 변이는 0곳 (파이썬에 ===·&& 가 없다)", by["unittest"]["mutation_hits"], 0)
check("CI 가 실행 계층을 돌린다", by["unittest"]["runs_in_ci"], True)
check("jest 도 여전히 CI 실행 O", by["jest"]["runs_in_ci"], True)
check("vitest·pytest 는 실행 계층이 CI 에 없다 (정직하게)",
      [by[n]["runs_in_ci"] for n in ("vitest", "pytest")], [False, False])

print("\n[9] CI 가 실행 계층을 선언하고 YAML 이 파싱되는가")
ci_path = PROJECT / ".github" / "workflows" / "ci.yml"
ci_text = ci_path.read_text(encoding="utf-8")
check("CI 가 실행 계층을 선언한다", "런너 실행 계층: unittest" in ci_text, True)
check("CI 가 coverage 를 설치한다", "pip install coverage" in ci_text, True)
check("CI 가 게이트를 두 기능에 돌린다",
      ci_text.count("--project verification/fixtures/unittest-app"), 2)
# 단계 이름에 `: ` 가 있으면 따옴표가 없으면 YAML 이 깨진다 — 실제로 깨뜨려 봤다
check("선언이 따옴표로 싸여 있다", '"런너 실행 계층: unittest' in ci_text, True)
try:
    import yaml

    doc = yaml.safe_load(ci_text)
    check("YAML 이 파싱된다", isinstance(doc.get("jobs"), dict), True)
    names = [s.get("name", "") for s in doc["jobs"]["harness"]["steps"]]
    check("선언 단계가 파싱 결과에 있다",
          any("런너 실행 계층: unittest" in n for n in names), True)
except ImportError:
    note_skip("PyYAML 이 없어 YAML 파싱 검사를 건너뜁니다")

print("\n[10] 문서가 실측한 함정을 담았는가")
doc = (PROJECT / "docs" / "adding-a-language.md").read_text(encoding="utf-8")
check("`name_pattern` 이 정규식임을 적는다", "정규식이다" in doc, True)
check("sys.path 함정을 적는다", "sys.path" in doc, True)
check("0개 선택이 측정 실패임을 적는다", "측정 실패" in doc, True)
check("출력 파싱 금지를 적는다", "파싱하지 말 것" in doc, True)
check("`inspect` 가 --harness-root 임을 바로잡았다", "--harness-root ./your-app" in doc, True)
check("게이트를 실제로 돌려보라고 적는다", "cli verify" in doc, True)
check("파이썬 계열은 태그 규약이 필수임을 적는다", "선택이 아니다" in doc, True)

print(f"{NL}{'=' * 60}")
print(f"TS-031 검증 결과: PASS {ok} / FAIL {fail}" +
      (f" / SKIP {skipped}" if skipped else ""))
print(f"{'=' * 60}")
sys.exit(1 if fail else 0)

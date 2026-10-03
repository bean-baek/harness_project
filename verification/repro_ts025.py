"""
TS-025 검증 스크립트 — 외부 프로젝트 모양에 하네스를 붙인다
─────────────────────────────────────────────────────────
**모든 검증이 단일 피험체(`web_target`)를 봤다.** 그 결과 두 번째 프로젝트에 닿는
순간 결함이 즉시 드러났고, 699개 검증은 **하나도** 잡지 못했다.

  `config_for` 가 harness_root 를 하드코딩    → 외부 `.harness.json` 무시 (5커밋 생존)
  pytest 접미사가 `test_.py` (접미사 비교)     → `test_app.py` 가 테스트로 인식 안 됨
  `_candidate_lines` 에 줄 커버리지 필터 없음  → 미실행 줄 변이가 생존으로 계수 (7커밋)

원인은 하나다 — **`web_target` 의 모양에 맞춰 검증을 만들면 다른 모양이 존재한다는
사실 자체가 테스트에 없다.** 이 스크립트가 그 구멍을 기계화한다.

픽스처는 `web_target` 과 **모든 칸이 다르다**:

  | | web_target | vanilla-js | pytest-app |
  |---|---|---|---|
  | 런너 | jest | vitest | pytest |
  | 단위 접미사 | `.test.tsx` | `.test.js` | `test_*.py` (접두사!) |
  | ID 형식 | `F-\\d{3}` | `APP-\\d{2}` | `PY-\\d{2}` |
  | 타입검사 | tsc | 없음 | 없음 |
  | 설정 위치 | 하네스 루트 | **프로젝트 자신** | **프로젝트 자신** |

정적 계층만 검증한다 — 런너를 설치하지 않는다. 그래도 위 세 결함 중 둘을 잡는다.
런너를 실제로 돌리는 계층은 `web_target`(jest)이 담당하고, vitest 는 실 프로젝트
(`main_portfolio`)에서 수동 확인했다. 그 격차를 아래 [8]에 명시한다.
"""
import json
import sys
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import deadcode, independence, project, tags
from harness import inspect as inspect_mod
from harness import verify

JS = PROJECT / "verification" / "fixtures" / "vanilla-js"
PY = PROJECT / "verification" / "fixtures" / "pytest-app"

ok = 0
fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


print("\n[1] 픽스처가 존재하고 web_target 과 다른 모양인가")
check("vanilla-js 픽스처 존재", (JS / ".harness.json").is_file(), True)
check("pytest-app 픽스처 존재", (PY / ".harness.json").is_file(), True)
js_raw = json.loads((JS / ".harness.json").read_text(encoding="utf-8"))
py_raw = json.loads((PY / ".harness.json").read_text(encoding="utf-8"))
own_raw = json.loads((PROJECT / ".harness.json").read_text(encoding="utf-8"))
check("런너가 셋 다 다르다",
      sorted({js_raw["runner"], py_raw["runner"], own_raw["runner"]}),
      ["jest", "pytest", "vitest"])
check("ID 형식이 셋 다 다르다",
      len({js_raw["id_pattern"], py_raw["id_pattern"], own_raw["id_pattern"]}), 3)
check("접미사 규약이 셋 다 다르다",
      len({tuple(js_raw["unit_suffixes"]), tuple(py_raw["unit_suffixes"]),
           tuple(own_raw["unit_suffixes"])}), 3)
check("pytest 픽스처는 **접두사** 규약을 쓴다", py_raw["unit_suffixes"], ["test_*.py"])

print("\n[2] 프로젝트 자신의 .harness.json 이 하네스 기본을 이기는가")
# 이것이 5커밋 동안 살아 있던 버그다 — config_for 가 config.BASE_DIR 를 하드코딩해
# 외부 프로젝트를 --project 로 지정하면 **이 레포의 설정**(jest)이 적용됐다.
project.clear_cache()
for label, path, want_runner, want_units in [
    ("vanilla-js", JS, "vitest", [".test.js"]),
    ("pytest-app", PY, "pytest", ["test_*.py"]),
]:
    cfg = verify.config_for(str(path))
    check(f"{label}: runner", cfg.runner, want_runner)
    check(f"{label}: unit_suffixes", cfg.unit_suffixes, want_units)
    check(f"{label}: typecheck 없음 (tsconfig 가 없다)", cfg.typecheck, [])
    check(f"{label}: target 은 넘긴 경로", Path(cfg.target).resolve(), path.resolve())

# web_target 은 자기 선언이 없으므로 하네스 기본으로 떨어진다 — 기존 동작 보존
cfg = verify.config_for("web_target")
check("web_target: 자기 선언 없음 → 하네스 기본(jest)", cfg.runner, "jest")
check("web_target: 접미사도 하네스 기본", cfg.unit_suffixes, [".test.ts", ".test.tsx"])
project.clear_cache()

print("\n[3] 태그 스캔이 각 프로젝트의 규약을 따르는가")
# pytest 접두사 규약이 깨져 있었다 — test_convert.py 가 테스트로 인식되지 않았다
project.clear_cache()
js_refs = tags.scan_tags(str(JS))
py_refs = tags.scan_tags(str(PY))
check("vanilla-js: 태그 발견", sorted({r.feature_id for r in js_refs}), ["APP-01", "APP-02"])
check("vanilla-js: 전부 단위로 분류", {r.kind for r in js_refs}, {"unit"})
check("pytest-app: **접두사 파일이 인식된다**",
      sorted({r.feature_id for r in py_refs}), ["PY-01", "PY-02"])
check("pytest-app: 테스트 파일을 찾았다",
      sorted({r.file for r in py_refs}), ["tests/test_convert.py"])
check("pytest-app: 전부 단위로 분류", {r.kind for r in py_refs}, {"unit"})
project.clear_cache()

print("\n[4] 접미사·접두사 규약 판정 (matches_pattern)")
m = tags.matches_pattern
check("접두사 글로브", m("test_app.py", ("test_*.py",)), True)
check("접미사 글로브", m("app_test.py", ("*_test.py",)), True)
check("conftest.py 는 테스트가 아니다", m("conftest.py", ("test_*.py", "*_test.py")), False)
check("평범한 접미사 (하위호환)", m("LoginForm.test.tsx", (".test.tsx",)), True)
check("접미사가 아니면 거부", m("LoginForm.ts", (".test.tsx",)), False)
check("깨진 옛 기본값은 매칭하지 않는다", m("test_app.py", ("test_.py",)), False)
check("빈 패턴 목록", m("x.py", ()), False)

print("\n[5] 명세를 프로젝트 자신의 파일에서 읽는가")
project.clear_cache()
for label, path, want_ids in [
    ("vanilla-js", JS, ["APP-01", "APP-02"]),
    ("pytest-app", PY, ["PY-01", "PY-02"]),
]:
    feats = verify.load_features(str(path))
    check(f"{label}: 명세 로드", [f["id"] for f in feats], want_ids)
    check(f"{label}: features_path 가 프로젝트 안을 가리킨다",
          verify.features_path(str(path)).parent.resolve(), path.resolve())
project.clear_cache()

print("\n[6] 게이트 판정 — 런너 없이 어디까지 가는가")
project.clear_cache()
for label, path in [("vanilla-js", JS), ("pytest-app", PY)]:
    runner = verify.runner_for(str(path))
    available, note = runner.available()
    check(f"{label}: 런너를 알아본다", runner.name,
          "vitest" if label == "vanilla-js" else "pytest")
    # vitest 는 package.json 에 선언만 돼 있고 설치되지 않았다 — 그 사실을 정확히 말해야 한다
    if label == "vanilla-js":
        check("vanilla-js: 선언됐으나 미설치를 구분한다",
              "npm install" in note, True)
project.clear_cache()

print("\n[7] 정적 검사가 외부 모양에서도 동작하는가")
project.clear_cache()
js_cfg = verify.config_for(str(JS))
colls = independence.declared_collections(str(JS), js_cfg)
check("vanilla-js: 선언된 컬렉션을 찾는다", [c.name for c in colls], ["PAGES"])
check("vanilla-js: 멤버 3개", len(colls[0].members) if colls else 0, 3)
res = independence.audit_independence(str(JS), verify.load_features(str(JS)))
check("독립성 분석이 돈다 (통과 기능 0건이므로 빈 목록)", res, [])

py_cfg = verify.config_for(str(PY))
py_colls = independence.declared_collections(str(PY), py_cfg)
check("pytest-app: 파이썬 리스트 선언도 컬렉션으로 본다",
      [c.name for c in py_colls], ["CURRENCIES"])
check("pytest-app: 멤버 3개", len(py_colls[0].members) if py_colls else 0, 3)
# 테스트가 `from src.convert import CURRENCIES` 로 앱의 선언을 읽는다 — 자급이 아니다.
# JS 의 named import 는 중괄호를 쓰므로 파이썬 분기가 없으면 여기서 오탐이 난다.
supplied = independence.self_supplied_in(
    PY / "tests" / "test_convert.py", PY, py_colls)
check("pytest-app: 파이썬 import 를 인식해 자급으로 오탐하지 않는다", supplied, [])
project.clear_cache()

print("\n[7b] 규약 판정을 쓰는 네 호출자가 모두 글로브를 처리하는가")
# `cfg.all_test_suffixes()` 를 `str.endswith` 에 바로 넣은 곳이 셋 있었고
# **셋 다 pytest 에서 틀렸다**. 규약 판정은 설정의 메서드 하나로 모았다.
py_cfg = verify.config_for(str(PY))
check("is_test_file: 접두사 규약 파일", py_cfg.is_test_file("test_convert.py"), True)
check("is_test_file: 소스 파일", py_cfg.is_test_file("convert.py"), False)
# inspect._test_files — 깨져 있을 때 빈 목록이었다
rep_py = inspect_mod.inspect_project(PY)
check("inspect: pytest 테스트 파일을 센다", rep_py.readiness.test_files >= 1, True)
check("inspect: 테스트를 소스로 세지 않는다",
      any("test_convert" in f for f in rep_py.readiness.untagged_sources
          if isinstance(f, str)) if hasattr(rep_py.readiness, "untagged_sources") else False,
      False)
# runner._is_source — 커버리지 집계에서 테스트 자신을 빼야 한다
py_runner = verify.runner_for(str(PY))
check("runner: 테스트 파일은 커버리지 증거가 아니다",
      py_runner._is_source("tests/test_convert.py"), False)
check("runner: 소스 파일은 증거다", py_runner._is_source("src/convert.py"), True)
# independence.declared_collections — 테스트가 소스로 섞이면 안 된다
check("independence: 테스트 파일에서 컬렉션을 긁어오지 않는다",
      all("test" not in c.declared_in for c in py_colls), True)
project.clear_cache()

print("\n[8] 픽스처가 하네스 자기 감사를 오염시키지 않는가")
# 픽스처의 .py 는 하네스가 호출하지 않으므로 고아로 보인다 — 범위에서 빼야 한다
check("deadcode.SKIP_DIRS 에 fixtures 포함", "fixtures" in deadcode.SKIP_DIRS, True)
# 두 집합은 **반대 방향**이다. `project.SKIP_DIRS` 는 검사 *대상* 안에서 무시할
# 디렉터리이고 `inspect` 가 그것을 쓴다 — 거기에 "fixtures" 가 들어가면 픽스처를
# 대상으로 지정했을 때 파일을 하나도 못 찾는다. 합치려는 시도를 여기서 막는다.
check("project.SKIP_DIRS 에는 fixtures 가 **없다** (합치면 안 된다)",
      "fixtures" in project.SKIP_DIRS, False)
check("두 집합은 서로 다른 객체다", deadcode.SKIP_DIRS is project.SKIP_DIRS, False)
audited = [str(p) for p in deadcode.python_files(PROJECT)]
check("픽스처의 .py 가 감사 대상에 없다",
      any("fixtures" in p for p in audited), False)
findings = deadcode.audit(PROJECT)
check("하네스 자기 감사 여전히 0건", len(findings), 0)

print("\n[9] 실제로 런너를 돌리는 계층의 격차 — 명시한다")
# 이 스크립트는 **정적 계층만** 본다. 런너 설치를 요구하지 않기 때문이다.
# 그 사실을 숨기지 않고 고정한다 (TS-016 의 규칙: 측정 못 한 것을 통과로 보지 않는다).
js_runner = verify.runner_for(str(JS))
# `launcher()` 는 npx 폴백으로 커맨드를 **만들 수 있다** (vite.config.js 가 있으므로).
# 그런데 패키지가 설치되지 않았으므로 `npx --no-install` 은 런타임에 실패한다.
# 이 둘을 가르는 것이 TS-017 의 3단 판정이고, 여기서 그 차이가 실제로 드러난다.
check("런처 커맨드는 만들어진다 (npx 폴백)", js_runner.launcher() is not None, True)
check("그러나 **실행 가능으로 보고하지 않는다** (미설치)",
      js_runner.available()[0], False)
print("        → 런너 실행 계층: jest 는 web_target 이, vitest 는 main_portfolio 실측이 담당.")
print("        → pytest 실행은 **아직 한 번도 하지 않았다** — 알려진 격차다.")

print("\n[10] 검수·초안이 외부 모양에서 동작하는가")
report = inspect_mod.inspect_project(JS)
check("vanilla-js 검수: 런너를 인식", report.readiness.runner, "vitest")
check("vanilla-js 검수: 테스트 파일을 센다", report.readiness.test_files >= 1, True)
check("vanilla-js 검수: 명세 기능 2개", report.readiness.spec_features, 2)
check("vanilla-js 검수: ID 형식이 전부 일치", report.readiness.spec_ids_matching, 2)
check("vanilla-js 검수: 런너 미설치를 막는 사유로 올린다",
      any("런너" in b for b in report.readiness.blockers), True)

print(f"\n{'='*60}")
print(f"TS-025 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

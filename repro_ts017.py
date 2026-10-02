"""
TS-017 검증 스크립트
────────────────────
**설정 외부화 · 런너 추상화 · 프로젝트 검수**를 검증한다.

  1) 설정이 없을 때 동작이 변하지 않는가 (기본값 == 외부화 이전 하드코딩)
  2) `.harness.json` — 선언 우선, 미지의 키 보고, 깨진 JSON 은 **조용히 넘기지 않음**
  3) 검수(detect) — 런너·접미사·타입검사 추론과 그 **근거**
  4) `config_for` — 호출자가 준 경로가 선언된 target 을 이긴다 (격리 보존)
  5) 런너 선택 — 모르는 런너는 예외, vitest 의 watch 함정 방어
  6) `available()` — 설치됨 / 선언만 됨 / 둘 다 아님을 구분 (거짓 '실행 가능' 방어)
  7) 결과 정규화 — 런너가 달라도 같은 모양
  8) 태그 — 프로젝트 ID 형식·접미사 규약을 따르는가
  9) 검수의 **오탐 방어** — 실측으로 잡은 두 건이 다시 나오지 않는가
 10) 명세 초안 — 출처가 박히는가, 자동 통과는 제외되는가

런너·tsc 를 실행하지 않는다. 전부 파일 조작과 정적 분석이다.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

import config
from harness import project
from harness import runner as runner_mod

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


def tmpdir(prefix="ts017-"):
    return Path(tempfile.mkdtemp(prefix=prefix))


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


print("\n[1] 설정 부재 시 동작 불변 — 기본값이 외부화 이전 하드코딩과 같은가")
d = project.ProjectConfig()
check("런너 기본값", d.runner, "jest")
check("단위 접미사 기본값", d.unit_suffixes, [".test.ts", ".test.tsx"])
check("E2E 접미사 기본값", d.e2e_suffixes, [".spec.ts", ".spec.tsx"])
check("ID 형식 기본값", d.id_pattern, "F-" + chr(92) + "d{3}")
check("명세 기본값", d.spec, "features.json")
empty = tmpdir()
cfg, findings = project.load(empty, detect_if_missing=False)
check("설정 파일 없으면 순수 기본값", cfg.to_dict(), d.to_dict())
check("검수 내역도 비어 있음", findings, [])

print("\n[2] .harness.json — 선언 우선 / 미지의 키 / 깨진 JSON")
root = tmpdir()
write(root / ".harness.json", json.dumps({
    "runner": "vitest",
    "id_pattern": "FEAT" + chr(92) + "d{4}",
    "unit_suffixes": [".spec.ts"],
    "typo_key": 1,
}, ensure_ascii=False))
cfg, findings = project.load(root, detect_if_missing=False)
check("선언된 런너가 이긴다", cfg.runner, "vitest")
check("선언된 ID 형식", cfg.id_pattern, "FEAT" + chr(92) + "d{4}")
check("선언된 접미사", cfg.unit_suffixes, [".spec.ts"])
check("선언 안 한 키는 기본값", cfg.spec, "features.json")
check("미지의 키를 보고한다", any("typo_key" in f.value for f in findings), True)
check("출처가 '선언'", all(f.source == "declared" for f in findings), True)

broken = tmpdir()
write(broken / ".harness.json", "{ not json")
try:
    project.load(broken, detect_if_missing=False)
    check("깨진 설정은 예외 (조용히 기본값으로 안 떨어진다)", False, True)
except ValueError as exc:
    check("깨진 설정은 예외 (조용히 기본값으로 안 떨어진다)", True, True)
    check("경로를 알려준다", ".harness.json" in str(exc), True)

notdict = tmpdir()
write(notdict / ".harness.json", "[1,2]")
try:
    project.load(notdict, detect_if_missing=False)
    check("최상위가 배열이면 예외", False, True)
except ValueError:
    check("최상위가 배열이면 예외", True, True)

print("\n[3] 검수(detect) — 추론과 근거")
# 3-1 의존성 선언이 설정 파일보다 우선
p1 = tmpdir()
write(p1 / "package.json", json.dumps({"devDependencies": {"vitest": "^1.0.0"}}))
write(p1 / "jest.config.ts", "export default {}")
c1, f1 = project.detect(p1)
check("의존성(vitest)이 jest 설정 파일을 이긴다", c1.runner, "vitest")
check("근거가 의존성을 지목", "의존성" in next(f.evidence for f in f1 if f.key == "runner"), True)

# 3-2 설치 안 됐지만 Vite 프로젝트 → vitest 제안 + 기본값 표시
p2 = tmpdir()
write(p2 / "package.json", json.dumps({"dependencies": {"vue": "^3"}}))
write(p2 / "vite.config.js", "export default {}")
c2, f2 = project.detect(p2)
check("Vite + 테스트 없음 → vitest 제안", c2.runner, "vitest")
check("출처는 '기본값' (실측 아님)",
      next(f.source for f in f2 if f.key == "runner"), "default")
check("게이트가 전부 거부한다고 경고",
      "거부" in next(f.evidence for f in f2 if f.key == "runner"), True)

# 3-3 pytest
p3 = tmpdir()
write(p3 / "pyproject.toml", "[tool.pytest.ini_options]\nminversion='7'\n")
write(p3 / "tests" / "test_a.py", "def test_x(): pass\n")
c3, f3 = project.detect(p3)
check("pytest 감지", c3.runner, "pytest")

# 3-4 접미사 실측 — E2E 전용 디렉터리는 증거에서 분리
p4 = tmpdir()
write(p4 / "package.json", json.dumps({"devDependencies": {"jest": "^29"}}))
write(p4 / "src" / "a.test.tsx", "x")
write(p4 / "src" / "b.test.tsx", "x")
write(p4 / "e2e" / "flow.spec.ts", "x")
c4, f4 = project.detect(p4)
check("단위 접미사 실측", c4.unit_suffixes, [".test.tsx"])
check("E2E 전용 경로의 .spec.ts 는 E2E 로 분리", c4.e2e_suffixes, [".spec.ts"])
check("실측 출처", next(f.source for f in f4 if f.key == "unit_suffixes"), "measured")

# 3-5 타입검사 — tsconfig 유무
p5 = tmpdir()
write(p5 / "package.json", json.dumps({"devDependencies": {"jest": "^29"}}))
c5, f5 = project.detect(p5)
check("tsconfig 없으면 타입검사 없음", c5.typecheck, [])
check("과대평가 경고를 남긴다",
      "과대평가" in next(f.evidence for f in f5 if f.key == "typecheck"), True)
write(p5 / "tsconfig.json", "{}")
c5b, _ = project.detect(p5)
check("tsconfig 있으면 tsc --noEmit", c5b.typecheck, ["npx", "--no-install", "tsc", "--noEmit"])

# 3-6 ID 형식을 명세에서 추론
p6 = tmpdir()
write(p6 / "features.json", json.dumps([{"id": "TASK-0012"}, {"id": "TASK-0099"}]))
pat, finding = project._guess_id_pattern(p6 / "features.json")
check("ID 형식 추론", bool(__import__("re").fullmatch(pat, "TASK-0012")), True)
check("자릿수까지 반영 (TASK-12 는 불일치)",
      bool(__import__("re").fullmatch(pat, "TASK-12")), False)
check("몇 개가 맞는지 보고", "2개가 이 형식" in finding.evidence, True)

print("\n[4] config_for — 호출자 경로가 선언된 target 을 이긴다")
project.clear_cache()
harness_root = tmpdir()
write(harness_root / ".harness.json", json.dumps({"target": "declared_app", "runner": "vitest"}))
caller = tmpdir()
got = project.config_for(caller, harness_root)
check("target 은 호출자 경로", got.target, str(caller.resolve()))
check("나머지 선언은 유지", got.runner, "vitest")
project.clear_cache()

print("\n[5] 런너 선택 — 모르는 런너와 vitest watch 함정")
try:
    runner_mod.for_project(project.ProjectConfig(runner="mocha"), tmpdir())
    check("모르는 런너는 예외", False, True)
except ValueError as exc:
    check("모르는 런너는 예외", True, True)
    check("지원 목록을 알려준다", "jest" in str(exc) and "pytest" in str(exc), True)
    check("확장 방법을 알려준다", "runner.py" in str(exc), True)

vt_root = tmpdir()
write(vt_root / "package.json", json.dumps({"devDependencies": {"vitest": "^1"}}))
write(vt_root / "vitest.config.ts", "export default {}")
bin_dir = vt_root / "node_modules" / ".bin"
write(bin_dir / "vitest.cmd", "@echo off")
vt = runner_mod.for_project(project.ProjectConfig(target=str(vt_root), runner="vitest"), vt_root)
launcher = vt.launcher()
check("vitest 런처에 'run' 이 있다 (watch 모드로 멈추지 않는다)", "run" in launcher, True)
check("vitest 는 --root (not --rootDir)", vt._root_args()[0], "--root")
check("jest 는 --rootDir", runner_mod.JestRunner(vt_root, project.ProjectConfig())._root_args()[0],
      "--rootDir")
cov_flags = " ".join(vt._coverage_flags("/tmp/x"))
check("vitest 커버리지 임계를 끈다", "thresholds.lines=0" in cov_flags, True)
check("jest 커버리지 임계를 끈다",
      "--coverageThreshold={}" in runner_mod.JestRunner(vt_root, project.ProjectConfig())._coverage_flags("/tmp/x"),
      True)

print("\n[6] available() — 거짓 '실행 가능' 방어")
# 6-1 로컬 바이너리 있음
check("로컬 바이너리 있으면 가능", vt.available()[0], True)
# 6-2 설정만 있고 미설치·미선언 (실측된 오탐: Vite 프로젝트가 '실행 가능'으로 나왔다)
bare = tmpdir()
write(bare / "package.json", json.dumps({"dependencies": {"vue": "^3"}}))
write(bare / "vite.config.js", "export default {}")
r_bare = runner_mod.for_project(project.ProjectConfig(target=str(bare), runner="vitest"), bare)
avail, note = r_bare.available()
check("미설치·미선언은 실행 불가", avail, False)
check("설치 방법을 알려준다", "npm install -D vitest" in note, True)
# 6-3 선언됐으나 미설치
declared_only = tmpdir()
write(declared_only / "package.json", json.dumps({"devDependencies": {"jest": "^29"}}))
r_decl = runner_mod.for_project(project.ProjectConfig(target=str(declared_only), runner="jest"),
                                declared_only)
avail2, note2 = r_decl.available()
check("선언만 됐으면 실행 불가", avail2, False)
check("npm install 을 지시", "npm install" in note2, True)

print("\n[7] 결과 정규화 — 런너가 달라도 같은 모양")
raw = {
    "numTotalTests": 5, "numPassedTests": 4, "numFailedTests": 1,
    "numTotalTestSuites": 2, "numFailedTestSuites": 1,
    "testResults": [{"assertionResults": [
        {"fullName": "F-001: 로그인", "status": "passed"},
        {"ancestorTitles": ["F-002: 오류"], "title": "메시지", "status": "failed"},
    ]}],
}
res = runner_mod._JsRunner._normalize(raw)
check("합계", (res.total, res.passed, res.failed), (5, 4, 1))
check("fullName 사용", res.assertions[0][0], "F-001: 로그인")
check("fullName 없으면 ancestor+title 합성", res.assertions[1][0], "F-002: 오류 메시지")
check("스위트 실패가 있으면 green 아님", res.green(), False)
check("green 판정", runner_mod.Results(total=3, passed=3).green(), True)
check("테스트 0건은 green 아님", runner_mod.Results().green(), False)

cov = runner_mod.Coverage({"A.tsx": 17, "B.tsx": 13})
check("커버리지 합계", cov.total(), 30)
check("상위 정렬", cov.top(1), ["A.tsx (17)"])

print("\n[8] 태그 — 프로젝트 규약을 따르는가")
from harness import tags

custom = project.ProjectConfig(
    runner="jest", id_pattern="TASK-" + chr(92) + "d{4}",
    unit_suffixes=[".check.ts"], e2e_suffixes=[".e2e.ts"],
)
tag_root = tmpdir()
write(tag_root / "x.check.ts", "describe('TASK-0012: 할 일', () => {\n"
                               "  test('TASK-0012.1: 첫 단계', () => {});\n});\n")
write(tag_root / "y.e2e.ts", "test('TASK-0099: E2E 전용', () => {});\n")
write(tag_root / "z.test.ts", "test('TASK-0013: 규약 밖 접미사', () => {});\n")
refs = tags.scan_tags(str(tag_root), custom)
ids = sorted({r.feature_id for r in refs})
check("커스텀 ID 형식 포착", ids, ["TASK-0012", "TASK-0099"])
check("커스텀 접미사 밖의 파일은 무시", "TASK-0013" in ids, False)
check("E2E 로 분류", next(r.kind for r in refs if r.feature_id == "TASK-0099"), "e2e")
check("단위로 분류", next(r.kind for r in refs if r.feature_id == "TASK-0012"), "unit")
check("단계 번호 포착", sorted({r.step for r in refs if r.step}), [1])
check("describe 는 스위트로 인식", any(r.is_suite for r in refs), True)
# ID 형식에 괄호가 들어와도 그룹 번호가 깨지지 않는다
grouped = tags.id_regex("(?:FEAT|BUG)-" + chr(92) + "d{2}")
m = grouped.search("BUG-07.3: x")
check("그룹1 = ID", m.group(1), "BUG-07")
check("그룹2 = 단계", m.group(2), "3")

print("\n[9] 검수의 오탐 방어 — 실측으로 잡은 두 건")
from harness import inspect as I

# 9-1 목록을 순회해 등록하면 '누락'이 아니다 (실측 오탐 1)
dyn = tmpdir()
write(dyn / "src" / "routes.ts",
      "export const PROTECTED_PATHS = ['/', '/dashboard', '/profile'] as const;\n")
write(dyn / "src" / "App.tsx",
      "import { PROTECTED_PATHS } from './routes';\n"
      "const R = () => (<Routes>\n"
      "  <Route path=\"/login\" element={<L />} />\n"
      "  {PROTECTED_PATHS.map((path) => (<Route key={path} path={path.slice(1)} />))}\n"
      "</Routes>);\n")
cfg_dyn = project.ProjectConfig(source_dirs=["src"])
checks = I.check_route_completeness(dyn, cfg_dyn)
check("순회 등록은 통과 (위반 아님)", [c.verdict for c in checks], ["ok"])
check("근거: 구조적으로 불가능", "구조적으로" in checks[0].detail, True)
check("역방향(/login 미선언)을 위반으로 보고하지 않는다",
      any("login" in c.detail for c in checks), False)

# 9-2 리터럴 등록에서 누락은 진짜 위반
lit = tmpdir()
write(lit / "src" / "routes.ts", "export const PATHS = ['/a', '/b', '/c'];\n")
write(lit / "src" / "App.tsx",
      "<Route path=\"/a\" /><Route path=\"/b\" />\n")
checks = I.check_route_completeness(lit, cfg_dyn)
check("리터럴 누락은 위반", checks[0].verdict, "violated")
check("빠진 경로를 지목", "/c" in checks[0].detail, True)

# 9-3 변수 경로가 섞이면 판정하지 않는다
mixed = tmpdir()
write(mixed / "src" / "routes.ts", "export const PATHS = ['/a', '/b'];\n")
write(mixed / "src" / "App.tsx",
      "<Route path=\"/a\" /><Route path={other} />\n")
checks = I.check_route_completeness(mixed, cfg_dyn)
check("동적 등록이 섞이면 판정 보류", checks[0].verdict, "needs-intent")
check("자동 판정 대상 아님", checks[0].auto, False)

# 9-4 `type X` 인라인 한정자 (실측 오탐 2)
ty = tmpdir()
write(ty / "src" / "routes.ts",
      "export const PATHS = ['/a','/b'];\nexport type ProtectedPath = string;\n")
write(ty / "src" / "App.tsx",
      "import { PATHS, type ProtectedPath } from './routes';\n"
      "const x: Record<ProtectedPath, number> = {};\n")
checks = I.check_unreferenced_exports(ty, cfg_dyn)
check("`type X` import 를 참조로 인정", checks[0].verdict, "ok")

# 9-5 진짜 미참조는 잡는다
dead = tmpdir()
write(dead / "src" / "api.ts", "export const authApi = 1;\nexport const used = 2;\n")
write(dead / "src" / "App.tsx", "import { used } from './api';\n")
checks = I.check_unreferenced_exports(dead, cfg_dyn)
check("진짜 미참조는 위반", checks[0].verdict, "violated")
check("이름을 지목", "authApi" in checks[0].detail, True)
check("한계를 함께 출력(재export·동적 import)", "동적 import" in checks[0].detail, True)

# 9-6 죽은 npm 스크립트 (TS-012 재현)
sc = tmpdir()
write(sc / "package.json", json.dumps({
    "scripts": {"good": "vite build", "dead": "jest --coverage", "builtin": "node x.js"},
    "devDependencies": {"vite": "^5"},
}))
checks = {c.claim.split("'")[1]: c for c in I.check_dead_scripts(sc)}
check("의존성 있는 스크립트는 통과", checks["good"].verdict, "ok")
check("의존성 없는 스크립트는 위반", checks["dead"].verdict, "violated")
check("jest 를 지목", "jest" in checks["dead"].detail, True)
check("node 같은 내장은 통과", checks["builtin"].verdict, "ok")

# 9-7 테스트가 import 하지 않는 소스
ut = tmpdir()
write(ut / "src" / "a.ts", "export const a = 1;\n")
write(ut / "src" / "b.ts", "export const b = 2;\n")
write(ut / "src" / "a.test.ts", "import { a } from './a';\n")
checks = I.check_untested_sources(ut, project.ProjectConfig(source_dirs=["src"]))
check("import 안 된 소스를 잡는다", checks[0].verdict, "violated")
check("b.ts 를 지목", "b.ts" in checks[0].detail, True)
check("a.ts 는 지목하지 않는다", "a.ts" in checks[0].detail.replace("b.ts", ""), False)

print("\n[10] 명세 초안 — 출처가 박히는가")
draft = I.draft_spec(tmpdir(), project.ProjectConfig(), [
    I.Check("dead-script", "A", verdict="violated", auto=True),
    I.Check("form-rules", "B", verdict="needs-intent", auto=False),
    I.Check("untested-source", "C", verdict="ok", auto=True),
])
check("자동 통과 항목은 초안에서 제외", len(draft), 2)
check("출처가 박힌다", draft[0]["origin"], "inspect:dead-script")
check("검토 필요 표시", all(d["needs_review"] for d in draft), True)
check("통과로 시작하지 않는다", all(d["passes"] is False for d in draft), True)
check("ID 접두사 반영", draft[0]["id"], "F-001")
draft2 = I.draft_spec(tmpdir(), project.ProjectConfig(id_pattern="TASK-" + chr(92) + "d{4}"), [
    I.Check("form-rules", "B", verdict="needs-intent", auto=False),
])
check("커스텀 접두사 반영", draft2[0]["id"], "TASK-001")

print("\n[11] 게이트 준비 상태 — 막는 것을 전부 열거하는가")
ready = tmpdir()
write(ready / "package.json", json.dumps({"dependencies": {}}))
r = I.assess_readiness(ready, project.ProjectConfig(target=str(ready)), ready)
check("테스트 0개를 막는 사유로 올린다",
      any("테스트 파일이 0개" in b for b in r.blockers), True)
check("명세 부재를 막는 사유로 올린다",
      any("명세" in b for b in r.blockers), True)
check("런너 불가를 막는 사유로 올린다",
      any("런너" in b for b in r.blockers), True)
check("붙일 수 없다고 판정", r.attachable(), False)

print(f"\n{'='*60}")
print(f"TS-017 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

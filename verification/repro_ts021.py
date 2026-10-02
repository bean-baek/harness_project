"""
TS-021 검증 스크립트 — 변이 연산자 수정 + 돌연변이 게이트
─────────────────────────────────────────────────────────
두 가지를 검증한다.

  1) **변이 연산자가 구문을 유지하는가** — 이전 구현은 그러지 않았다.
     `>` → `>=` 규칙이 190곳에 매칭됐고 진짜 비교는 3곳뿐이었다. 나머지는
     JSX 태그(108곳)와 제네릭(32곳)이라 치환하면 `React.FC<Props>=` 가 됐다.
     `if (X)` → `if (false)` 는 중첩 괄호에서 `if (false))` 로 깨졌다(26곳 중 5곳).
     변이가 테스트를 시험하는 게 아니라 **컴파일러를 시험**했고, '폐기' 집계가
     그 사실을 가렸다.

  2) **돌연변이가 게이트로 작동하는가** — 기준은 "유효한 변이 1개 이상을 잡는다".
     TS-016 의 "소스 1줄 이상 실행"과 같은 모양의 최솟값이며 비율이 아니다.

jest·tsc 는 전부 스텁한다. 실제 실행·LLM 호출 없음.
"""
import json
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import config
from harness import mutate, verify

ok = 0
fail = 0
NL = chr(10)


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


def balanced(s: str) -> bool:
    return s.count("(") == s.count(")")


print("\n[1] `if (X)` 무력화 — 괄호를 세어 균형을 지키는가")
n = mutate.neutralize_condition
cases = [
    ("중첩 1단", "if (!re.test(email)) return x;", "if (false) return x;"),
    ("중첩 + 논리", "if (!t || !t.startsWith('/')) return '/';", "if (false) return '/';"),
    ("깊은 중첩", "if (a.current && !a.current.contains(e.target as Node)) {", "if (false) {"),
    ("단순", "if (fullPage) {", "if (false) {"),
    ("else if", "  } else if (a && b) {", "  } else if (false) {"),
]
for label, src, want in cases:
    got = n(src)
    check(f"{label}", got, want)
    check(f"{label} — 괄호 균형", balanced(got or ""), True)

# 문자열 리터럴 안의 괄호에 속지 않는다
check("문자열 안 ')' 무시", n('if (s === "a)b") {'), "if (false) {")
check("여러 줄 조건은 건너뜀 (None)", n("if (cond &&"), None)
check("if 가 없으면 None", n("const x = 1;"), None)
check("백틱 문자열도 처리", n("if (t === `a)b`) {"), "if (false) {")

print("\n[2] `>` → `>=` — 진짜 비교만 고르는가")
import re

pat = next(p for name, p, _ in mutate.MUTATIONS if name.startswith("경계 이동"))
rx = re.compile(pat)
# 걸려야 하는 것
for label, line in [
    ("단순 비교", "if (unreadCount > 0) {"),
    ("식 비교", "if (payload.exp * 1000 > Date.now()) {"),
    ("삼항 안 비교", "const m = a.x > b.x ? a : b;"),
]:
    check(f"포착: {label}", bool(rx.search(line)), True)
# 걸리면 안 되는 것 — 이전 구현이 전부 망가뜨렸다
for label, line in [
    ("제네릭", "export const C: React.FC<Props> = ({}) => {"),
    ("JSX 자기닫기", "  <DashboardPage />,"),
    ("JSX 여는태그", "  <div className='x'>"),
    ("JSX 닫는태그", "  </Routes>"),
    ("화살표 함수", "const f = (a) => a + 1;"),
    ("중첩 제네릭", "const m: Record<Path, React.ReactNode> = {};"),
    ("타입 단정", "as Array<string>"),
]:
    check(f"제외: {label}", bool(rx.search(line)), False)

print("\n[3] 치환이 실제로 구문을 유지하는가 (전수)")
# 실제 대상 앱의 소스 전체에 각 규칙을 적용해 괄호/꺾쇠 균형이 깨지지 않는지 본다
src_dir = PROJECT / "web_target" / "src"
files = [p for p in sorted(src_dir.rglob("*.ts*")) if ".test." not in p.name]
broken: list[str] = []
applied_total = 0
for p in files:
    text = p.read_text(encoding="utf-8")
    for rule, pattern, repl in mutate.MUTATIONS:
        for lineno in mutate._candidate_lines(text, pattern):
            line = text.split(NL)[lineno - 1]
            if repl is None:
                new = n(line)
                if new is None:
                    continue
            else:
                new = re.sub(pattern, repl, line, count=1)
            if new == line:
                continue
            applied_total += 1
            # 올바른 불변식은 **개수 동일**이 아니라 **순증감(delta) 동일**이다.
            # `if (!re.test(email))` → `if (false)` 는 괄호 개수가 2→1 로 줄지만
            # 균형은 유지된다 (하위 식을 통째로 지웠으니 당연하다). 깨진 구현이
            # 만들던 `if (false))` 는 delta 가 0 → -1 로 바뀌므로 이 기준에 걸린다.
            def delta(s: str, o: str, c: str) -> int:
                return s.count(o) - s.count(c)

            if delta(new, "(", ")") != delta(line, "(", ")"):
                broken.append(f"{p.name}:{lineno}  {rule}  괄호 delta 변화  {line.strip()[:44]}")
            # 꺾쇠 검사는 **치환 규칙에만** 적용한다 (repl is not None).
            # 조건 무력화는 조건을 통째로 지우므로 그 안의 비교 연산자(`< 8` 등)가
            # 함께 사라지는 것이 정상이다 — `if (password.length < 8)` → `if (false)`.
            # 반면 치환 규칙이 꺾쇠를 건드리면 제네릭/JSX 파괴이고, 그것이 TS-021 의
            # 본 문제였다 (`React.FC<Props>` → `React.FC<Props>=`).
            if repl is not None and (new.count("<") != line.count("<")
                                     or new.count(">") != line.count(">")):
                broken.append(f"{p.name}:{lineno}  {rule}  꺾쇠 변화  {line.strip()[:44]}")
check("적용 가능한 변이가 존재한다", applied_total > 20, True)
check("구문 균형을 깨는 변이 0건", len(broken), 0)

# 깨진 구현이 실제로 이 기준에 걸리는지 확인 — 기준이 작동함을 입증한다
old_if_pattern = r"if \(([^)]{1,80})\)"
victim = "if (!emailRegex.test(email)) return 'x';"
old_result = re.sub(old_if_pattern, "if (false)", victim, count=1)
check("깨진 구현의 결과물", old_result, "if (false)) return 'x';")
check("그것이 delta 기준에 걸린다",
      (old_result.count("(") - old_result.count(")"))
      != (victim.count("(") - victim.count(")")), True)
old_gt = r"(?<![<>=!])>(?![=>])"
victim2 = "export const C: React.FC<Props> = ({}) => {"
old_result2 = re.sub(old_gt, ">=", victim2, count=1)
check("깨진 `>` 규칙이 제네릭을 파괴했다", "Props>=" in old_result2, True)
check("새 `>` 규칙은 그 줄을 건드리지 않는다", bool(rx.search(victim2)), False)
for b in broken[:5]:
    print(f"        {b}")

print("\n[4] 검사 순서 — 생존 변이는 tsc 를 건너뛰는가 (비용)")
calls: list[str] = []
orig_tc, orig_tf = mutate._typechecks, mutate._tests_fail
orig_tagged, orig_cov = mutate.tagged_test_files, mutate.coverage_for_feature

work = Path(tempfile.mkdtemp(prefix="ts021-"))
(work / "src").mkdir(parents=True)
TARGET_SRC = NL.join([
    "export const f = (a: number, b: number) => {",
    "  if (a === b) { return true; }",
    "  return a > b && b !== 0;",
    "};",
    "",
])
(work / "src" / "Thing.tsx").write_text(TARGET_SRC, encoding="utf-8")
(work / "features.json").write_text("[]", encoding="utf-8")

mutate.tagged_test_files = lambda pr, fid: ["src/Thing.test.tsx"]
mutate.coverage_for_feature = lambda pr, fid, top_n=5, test_files=None: (
    {"covered_statements": 3, "files_touched": 1, "sources": ["Thing.tsx (3)"]}, "")
try:
    mutate._typechecks = lambda pr: (calls.append("tsc"), True)[1]
    mutate._tests_fail = lambda pr, f, t: (calls.append("jest"), False)[1]   # 전부 생존
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("생존만 나오면 tsc 호출 0회", calls.count("tsc"), 0)
    check("jest 는 변이마다 호출", calls.count("jest"), len(rep["mutants"]))
    check("전부 생존으로 집계", (rep["killed"], rep["survived"]), (0, len(rep["mutants"])))

    calls.clear()
    mutate._tests_fail = lambda pr, f, t: (calls.append("jest"), True)[1]    # 전부 실패
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("실패하면 tsc 로 유효성을 확인한다", calls.count("tsc"), len(rep["mutants"]))
    check("타입 통과 + 테스트 실패 = 잡음", rep["killed"], len(rep["mutants"]))

    calls.clear()
    mutate._typechecks = lambda pr: (calls.append("tsc"), False)[1]          # 타입 깨짐
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("타입 실패 = 폐기 (잡음 아님)", (rep["killed"], rep["invalid"]),
          (0, len(rep["mutants"])))
    check("폐기는 점수 분모에서 제외", rep["score"], None)

    check("원본 완전 복원",
          (work / "src" / "Thing.tsx").read_text(encoding="utf-8"), TARGET_SRC)
finally:
    mutate._typechecks, mutate._tests_fail = orig_tc, orig_tf
    mutate.tagged_test_files, mutate.coverage_for_feature = orig_tagged, orig_cov

print("\n[5] 돌연변이 게이트 — 잡음 0건이면 거부하는가")
orig_json, orig_vcov = verify.run_jest_json, verify.coverage_for_feature
orig_flag = config.REQUIRE_MUTATION_EVIDENCE
orig_mf = None


def fresh_project():
    root = Path(tempfile.mkdtemp(prefix="ts021-gate-"))
    (root / "features.json").write_text(json.dumps([
        {"id": "C-001", "description": "기능 하나", "passes": False, "steps": ["s1"]},
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    return root


verify.run_jest_json = lambda pr: ({
    "numTotalTests": 2, "numPassedTests": 2, "numFailedTests": 0,
    "numTotalTestSuites": 1, "numFailedTestSuites": 0,
    "testResults": [{"assertionResults": [
        {"fullName": "C-001.1: 단계 1", "title": "x", "ancestorTitles": [], "status": "passed"},
        {"fullName": "무관", "title": "y", "ancestorTitles": [], "status": "passed"},
    ]}],
}, "")
verify.coverage_for_feature = lambda *a, **k: (
    {"covered_statements": 30, "files_touched": 1, "sources": ["Thing.tsx (30)"]}, "")

import harness.mutate as mut_mod
try:
    config.REQUIRE_MUTATION_EVIDENCE = True
    orig_mf = mut_mod.mutate_feature

    # 5-A 잡음 0건 → 거부
    mut_mod.mutate_feature = lambda pr, fid, max_files=2: {
        "feature": fid, "sources": ["Thing.tsx (30)"], "mutants": [],
        "killed": 0, "survived": 4, "invalid": 0, "score": 0.0}
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    check("잡음 0건 거부", applied, False)
    check("사유: 결함을 잡지 못했다", "하나도 잡지 못했습니다" in msg, True)
    check("플래그 변경 없음",
          json.loads((root / "features.json").read_text(encoding="utf-8"))[0]["passes"], False)

    # 5-B 잡음 1건 → 통과 + 기록
    mut_mod.mutate_feature = lambda pr, fid, max_files=2: {
        "feature": fid, "sources": ["Thing.tsx (30)"], "mutants": [],
        "killed": 1, "survived": 3, "invalid": 1, "score": 0.25}
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    feat = json.loads((root / "features.json").read_text(encoding="utf-8"))[0]
    check("잡음 1건이면 통과 (최솟값 기준)", applied, True)
    check("돌연변이 블록 기록", feat["verification"]["mutation"]["measured"], True)
    check("잡음·생존·폐기 기록",
          (feat["verification"]["mutation"]["killed"],
           feat["verification"]["mutation"]["survived"],
           feat["verification"]["mutation"]["invalid"]), (1, 3, 1))
    check("점수 기록", feat["verification"]["mutation"]["score"], 0.25)

    # 5-C 도구 오류 → 거부 (측정 실패는 통과가 아니다 — TS-016 의 규칙)
    mut_mod.mutate_feature = lambda pr, fid, max_files=2: {"error": "jest 를 찾을 수 없습니다"}
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    check("도구 오류는 거부", applied, False)
    check("원인 전달", "jest 를 찾을 수 없습니다" in msg, True)

    # 5-D 변이할 구문이 없음 → 거부하지 않고 기록 (측정 대상 부재 ≠ 측정 실패)
    mut_mod.mutate_feature = lambda pr, fid, max_files=2: {
        "feature": fid, "sources": ["Const.ts (5)"], "mutants": [],
        "killed": 0, "survived": 0, "invalid": 0, "score": None}
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    feat = json.loads((root / "features.json").read_text(encoding="utf-8"))[0]
    check("변이 대상 부재는 거부하지 않는다", applied, True)
    check("측정하지 못했음을 기록", feat["verification"]["mutation"]["measured"], False)
    check("사유를 기록", "구문이 없습니다" in feat["verification"]["mutation"]["reason"], True)

    # 5-E 게이트를 끄면 측정 자체를 건너뛴다
    config.REQUIRE_MUTATION_EVIDENCE = False
    seen: list[int] = []
    mut_mod.mutate_feature = lambda pr, fid, max_files=2: (seen.append(1), {"error": "x"})[1]
    root = fresh_project()
    applied, msg = verify.apply_flag(str(root), 0, passes=True)
    check("끈 상태에서 반영됨", applied, True)
    check("돌연변이 측정을 호출하지 않음", seen, [])
    check("돌연변이 블록도 없음",
          "mutation" in json.loads(
              (root / "features.json").read_text(encoding="utf-8"))[0]["verification"], False)
finally:
    verify.run_jest_json, verify.coverage_for_feature = orig_json, orig_vcov
    config.REQUIRE_MUTATION_EVIDENCE = orig_flag
    if orig_mf is not None:
        mut_mod.mutate_feature = orig_mf

print("\n[6] 기본값 — 켜는 것은 운영자의 선택")
check("기본값은 false (기능당 약 27초)", config.REQUIRE_MUTATION_EVIDENCE, False)
check("환경변수로 켠다", "HARNESS_REQUIRE_MUTATION_EVIDENCE" in
      (PROJECT / "config.py").read_text(encoding="utf-8"), True)

print("\n[7] 실제 레포 — 기록된 측정값이 기준을 만족하는가")
feats = json.loads((PROJECT / "web_target" / "features.json").read_text(encoding="utf-8"))
measured = [f for f in feats
            if f.get("passes") and (f.get("verification") or {}).get("mutation")]
check("돌연변이가 기록된 기능이 있다", len(measured) >= 1, True)
for f in measured:
    m = f["verification"]["mutation"]
    if m.get("measured"):
        check(f"{f['id']}: 잡음 1건 이상 (게이트 기준)", m["killed"] >= 1, True)
        check(f"{f['id']}: 폐기 0건 (연산자가 구문을 유지한다)", m["invalid"], 0)

print(f"\n{'='*60}")
print(f"TS-021 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

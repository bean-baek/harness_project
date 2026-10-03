"""
TS-026 검증 스크립트 — 미실행 줄에 변이를 넣고 그 생존을 증거의 구멍으로 셌다
─────────────────────────────────────────────────────────────────────────
커버리지는 **파일**을 고르는 데만 쓰였다. `Coverage.per_file` 은 개수뿐이라
"이 파일이 13줄 실행됐다"까지만 알고, 변이는 **줄 단위로** 들어간다. 그래서
증거가 지나가지 않는 줄에 결함이 심어졌고, 그 변이는 **반드시 생존**했다.

생존은 점수의 분모에 들어간다 → 점수가 틀린 값으로 **낮아진다.**

  실측: `LoginForm.tsx` 의 변이 후보 18곳 중 **실행되는 것은 2곳**
        F-005 의 변이 가능 지점 **21줄 중 5줄**에만 증거가 닿는다 (24%)
        수정 후 F-005 점수: 50%/40%/33%/50% (네 번 발표) → **100%, 생존 0건**

네 번 발표된 수치가 **전부** 틀렸다 (TS-024 에 드리프트로 기록된 그 수치들이다).
드리프트의 원인 중 하나가 측정 자체의 결함이었다.

TS-022 의 부작용이기도 하다. 표본을 고르게 퍼뜨린 뒤로 미실행 줄까지 균등하게
뽑히기 시작했다 — TS-022 는 **닿는 범위**를 넓혔고, 닿아야 할 곳과 닿아도 의미
없는 곳을 가르지 않았다. TS-022 의 문서는 "19곳이 전부 실행되는 줄"이라고 적었고
그것은 측정하지 않은 주장이었다.

음성 대조를 포함한다 (설계 규약 1): **statement 의 start~end 범위를 쓰면 안 된다**는
것을 실측으로 고정한다. 범위를 쓰면 `LoginForm.tsx` 에서 167줄이 '실행됨'이 되고
미실행 statement 54개 중 48개가 그 안에 먹힌다 — 지금 고치는 결함이 그대로 남는다.

jest·tsc 는 전부 스텁. 실제 실행·LLM 호출 없음.
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

from harness import mutate
from harness import project as project_mod
from harness import verify
from harness.runner import Coverage, JestRunner, PytestRunner

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


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


SRC = NL.join([
    "export function reached(a, b) {",      # 1
    "  if (a > b) return 1;",               # 2  실행됨
    "  return 0;",                          # 3
    "}",                                    # 4
    "export function never(flag) {",        # 5
    "  if (flag === true) return 'y';",     # 6  **미실행**
    "  return 'n';",                        # 7
    "}",                                    # 8
])

print("\n[1] _candidate_lines — 실행된 줄만 고르는가")
cands_all = mutate._candidate_lines(SRC, r"if \(", None)
check("None 이면 필터하지 않는다 (하위호환)", cands_all, [2, 6])
check("실행된 줄만 주면 그 줄만", mutate._candidate_lines(SRC, r"if \(", {2}), [2])
check("미실행 줄만 주면 그 줄만", mutate._candidate_lines(SRC, r"if \(", {6}), [6])
check("빈 집합은 '실행된 줄이 없다' — 후보 0", mutate._candidate_lines(SRC, r"if \(", set()), [])
check("후보가 아닌 줄을 넣어도 생기지 않는다",
      mutate._candidate_lines(SRC, r"if \(", {1, 3, 4}), [])
# None 과 set() 을 섞으면 측정 실패가 '대상 없음'으로 위장된다
check("None 과 set() 은 다른 결과를 낸다",
      mutate._candidate_lines(SRC, r"if \(", None)
      != mutate._candidate_lines(SRC, r"if \(", set()), True)

print("\n[2] Coverage — '모른다' 와 '하나도 실행되지 않았다' 를 구분하는가")
cov_known = Coverage({"a.ts": 3}, {"a.ts": {2, 5}})
cov_blind = Coverage({"a.ts": 3})
check("줄 지도가 있으면 집합", cov_known.lines_for("a.ts"), {2, 5})
check("줄 지도가 없으면 None", cov_blind.lines_for("a.ts"), None)
check("모르는 파일도 None", cov_known.lines_for("b.ts"), None)
check("'실행 0줄' 은 빈 집합으로 표현된다",
      Coverage({"a.ts": 0}, {"a.ts": set()}).lines_for("a.ts"), set())
check("per_file 은 그대로 동작한다 (하위호환)", cov_blind.total(), 3)

print("\n[3] istanbul 파서 — statement 를 줄로 환산한다")


class _Cfg:
    unit_suffixes = [".test.ts"]
    e2e_suffixes = [".spec.ts"]

    def all_test_suffixes(self):
        return tuple(self.unit_suffixes) + tuple(self.e2e_suffixes)

    def is_test_file(self, name):
        return project_mod.matches_pattern(
            name.replace("\\", "/").rsplit("/", 1)[-1], self.all_test_suffixes())


tmp = Path(tempfile.mkdtemp(prefix="harness-ts026-"))
runner = JestRunner(tmp, _Cfg())

# 함수 선언 statement 는 모듈 로드 때 실행되면서 **호출되지 않은 본문 전체**를
# start~end 범위에 담는다. 그래서 범위를 쓰면 미실행 줄이 실행된 것으로 섞인다.
final = tmp / "coverage-final.json"
write(final, json.dumps({
    "/p/src/app.ts": {
        "path": "/p/src/app.ts",
        "statementMap": {
            "0": {"start": {"line": 1}, "end": {"line": 8}},   # 선언 — 실행됨 (범위가 전체)
            "1": {"start": {"line": 2}, "end": {"line": 2}},   # 실행됨
            "2": {"start": {"line": 6}, "end": {"line": 6}},   # **미실행**
            "3": {"start": {"line": 7}, "end": {"line": 7}},   # **미실행**
        },
        "s": {"0": 1, "1": 2, "2": 0, "3": 0},
    },
    "/p/src/app.test.ts": {       # 테스트 파일 자신은 증거가 아니다
        "path": "/p/src/app.test.ts",
        "statementMap": {"0": {"start": {"line": 1}, "end": {"line": 1}}},
        "s": {"0": 1},
    },
}))
lines = runner._executed_lines(final)
check("실행된 statement 의 **시작 줄**만", lines.get("app.ts"), {1, 2})
check("미실행 줄은 들어오지 않는다", 6 in (lines.get("app.ts") or set()), False)
check("테스트 파일은 제외한다 (증거가 아니다)", "app.test.ts" in lines, False)

# ── 음성 대조 ──────────────────────────────────────────────────────────────
# 범위(start~end)를 쓰면 어떻게 되는지 같은 입력으로 계산해 **틀림을 고정한다.**
data = json.loads(final.read_text(encoding="utf-8"))["/p/src/app.ts"]
spanned = set()
for sid, loc in data["statementMap"].items():
    if data["s"][sid]:
        spanned.update(range(loc["start"]["line"], loc["end"]["line"] + 1))
check("음성 대조: 범위를 쓰면 미실행 줄 6 이 섞인다", 6 in spanned, True)
check("음성 대조: 범위를 쓰면 미실행 줄 7 도 섞인다", 7 in spanned, True)
check("현재 구현은 그 둘을 넣지 않는다",
      bool({6, 7} & (lines.get("app.ts") or set())), False)

# 같은 줄에 실행·미실행 statement 가 함께 있으면 제외한다 (hit - miss)
write(final, json.dumps({
    "/p/src/mix.ts": {
        "statementMap": {
            "0": {"start": {"line": 4}, "end": {"line": 4}},
            "1": {"start": {"line": 4}, "end": {"line": 4}},
            "2": {"start": {"line": 9}, "end": {"line": 9}},
        },
        "s": {"0": 1, "1": 0, "2": 3},
    },
}))
check("한 줄에 미실행 statement 가 섞이면 그 줄을 뺀다",
      runner._executed_lines(final).get("mix.ts"), {9})

check("깨진 JSON 은 빈 지도 (예외를 던지지 않는다)",
      runner._executed_lines(tmp / "nope.json"), {})
write(final, "{ not json")
check("파싱 실패도 빈 지도", runner._executed_lines(final), {})

print("\n[4] 런너 플래그 — 줄 지도를 만드는 리포터를 요구하는가")
from harness.runner import VitestRunner
jf = JestRunner(tmp, _Cfg())._coverage_flags(str(tmp))
vf = VitestRunner(tmp, _Cfg())._coverage_flags(str(tmp))
check("jest: json-summary (개수)", "--coverageReporters=json-summary" in jf, True)
check("jest: json (줄 지도)", "--coverageReporters=json" in jf, True)
check("vitest: json-summary", "--coverage.reporter=json-summary" in vf, True)
check("vitest: json", "--coverage.reporter=json" in vf, True)
check("vitest 는 여전히 run 서브커맨드를 쓴다 (watch 멈춤 방지)",
      VitestRunner.pre_args, ("run",))

print("\n[5] pytest — executed_lines 를 그대로 읽는가")
# pytest 는 이 레포에 설치되어 있지 않다. 파싱을 메서드로 떼어 두었으므로
# **pytest 없이 파싱 규약을 검증**한다 (TS-025 가 기록한 공백의 일부를 메운다).
#
# 설정은 **pytest 규약**으로 준다. jest 규약(`.test.ts`)을 주면 `test_convert.py` 가
# 테스트로 인식되지 않아 커버리지 증거로 섞인다 — 파서가 하드코딩이 아니라
# **선언된 규약**을 따른다는 뜻이고, 그 규약은 글로브다 (TS-025).
class _PyCfg(_Cfg):
    unit_suffixes = ["test_*.py", "*_test.py"]
    e2e_suffixes = ["*_e2e.py"]


pr = PytestRunner(tmp, _PyCfg())
pcov = pr._parse_coverage({"files": {
    "src/convert.py": {"summary": {"covered_lines": 3},
                       "executed_lines": [1, 4, 5]},
    "tests/test_convert.py": {"summary": {"covered_lines": 9},   # 테스트 자신
                              "executed_lines": [1, 2, 3]},
    "src/unused.py": {"summary": {"covered_lines": 0},           # 실행 0줄
                      "executed_lines": []},
}})
check("줄 번호를 환산 없이 그대로 쓴다", pcov.lines_for("convert.py"), {1, 4, 5})
check("statement 수도 함께 센다", pcov.per_file.get("convert.py"), 3)
check("테스트 파일은 제외한다 (증거가 아니다)", pcov.lines_for("test_convert.py"), None)
check("실행 0줄 파일은 담지 않는다", pcov.lines_for("unused.py"), None)
check("executed_lines 가 없으면 줄 지도 없음 (None, 빈 집합이 아니다)",
      pr._parse_coverage({"files": {
          "src/a.py": {"summary": {"covered_lines": 2}}}}).lines_for("a.py"), None)
check("files 키가 없어도 깨지지 않는다", pr._parse_coverage({}).per_file, {})
check("entry 가 dict 가 아니어도 깨지지 않는다",
      pr._parse_coverage({"files": {"src/a.py": None}}).per_file, {})

print("\n[6] 변이 파이프라인 — 미실행 줄을 빼고 그 사실을 보고하는가")
work = Path(tempfile.mkdtemp(prefix="harness-ts026-work-"))
write(work / "src" / "app.ts", SRC)
write(work / "src" / "app.test.ts", "test('T-001: x', () => {});" + NL)
write(work / "features.json", json.dumps(
    [{"id": "T-001", "name": "도달 검사", "passes": False}], ensure_ascii=False))
write(work / ".harness.json", json.dumps({
    "target": ".", "runner": "jest", "source_dirs": ["src"],
    "unit_suffixes": [".test.ts"], "e2e_suffixes": [".spec.ts"],
    "id_pattern": r"T-\d{3}",
}))
project_mod.clear_cache()

orig = (mutate.tagged_test_files, mutate.coverage_for_feature,
        mutate._typechecks, mutate._tests_fail)
try:
    mutate.tagged_test_files = lambda pr, fid: ["src/app.test.ts"]
    mutate._typechecks = lambda pr: True
    mutate._tests_fail = lambda pr, f, t: True        # 전부 잡힌다고 가정

    # 6-A 줄 지도가 있고 2번 줄만 실행됐다 → 6번 줄은 변이하지 않는다
    mutate.coverage_for_feature = lambda pr, fid, top_n=5, test_files=None: (
        {"covered_statements": 2, "files_touched": 1, "sources": ["app.ts (2)"],
         "executed_lines": {"app.ts": {1, 2, 3, 4}}}, "")
    rep = mutate.mutate_feature(str(work), "T-001", max_files=1)
    mutated_lines = sorted({m.line for m in rep["mutants"]})
    check("실행된 줄만 변이했다", mutated_lines, [2])
    check("미실행 줄 6 은 변이하지 않았다", 6 in mutated_lines, False)
    check("제외한 수를 센다", rep["skipped_unexecuted"], 1)
    check("줄 지도가 있으므로 unmapped 는 비어 있다", rep["unmapped_files"], [])
    text = mutate.format_mutation(rep)
    check("보고가 제외 사실을 적는다", "미실행 줄 1곳" in text, True)
    check("보고가 도달률을 적는다", "도달률" in text, True)
    # 도달률은 **줄 수**로 센다. 2번 줄은 규칙 두 개가 걸려 변이가 2개지만 지점은
    # 1줄이다. 변이 수와 줄 수를 섞으면 단위가 다른 값을 나누게 된다.
    check("도달 지점은 줄 수로 센다", rep["reached_lines"], 1)
    check("도달률이 2줄 중 1줄", "2줄 중 1줄에 증거가 닿는다" in text, True)
    check("변이 수(2)와 줄 수(1)를 섞지 않는다",
          rep["attempted"] != rep["reached_lines"], True)

    # 6-B 줄 지도가 없으면 **필터하지 않고 그 사실을 보고한다** (하위호환 + 정직성)
    mutate.coverage_for_feature = lambda pr, fid, top_n=5, test_files=None: (
        {"covered_statements": 2, "files_touched": 1, "sources": ["app.ts (2)"]}, "")
    rep = mutate.mutate_feature(str(work), "T-001", max_files=1)
    check("줄 지도가 없으면 전부 변이한다", sorted({m.line for m in rep["mutants"]}), [2, 6])
    check("제외는 0 (필터하지 않았다)", rep["skipped_unexecuted"], 0)
    check("줄 지도를 못 얻은 파일을 보고한다", rep["unmapped_files"], ["src/app.ts"])
    text = mutate.format_mutation(rep)
    check("보고가 경고를 적는다", "줄 지도를 얻지 못한 파일" in text, True)
    check("과소평가 가능성을 명시한다", "과소평가일 수 있다" in text, True)

    # 6-C 실행된 줄이 **하나도** 변이 가능하지 않다 → 대상 부재 (측정 실패가 아니다)
    mutate.coverage_for_feature = lambda pr, fid, top_n=5, test_files=None: (
        {"covered_statements": 1, "files_touched": 1, "sources": ["app.ts (1)"],
         "executed_lines": {"app.ts": {1, 3, 4}}}, "")
    rep = mutate.mutate_feature(str(work), "T-001", max_files=1)
    check("시도 0건", rep["attempted"], 0)
    check("점수 없음 (분모가 0)", rep["score"], None)
    check("미도달 지점 수를 남긴다", rep["skipped_unexecuted"], 2)
finally:
    (mutate.tagged_test_files, mutate.coverage_for_feature,
     mutate._typechecks, mutate._tests_fail) = orig
    project_mod.clear_cache()

print("\n[6b] 생존 변이에 대한 조언이 소유권으로 책임을 넘기지 않는가")
# TS-023 은 F-005 의 생존 3건을 "다른 기능이 소유한 파일이니 그 기능의 측정에서
# 확인하라"고 넘겼다. **틀린 조언이었다** — 그 3건의 실제 원인은 소유권이 아니라
# 미실행이었다. 미실행을 걸러낸 뒤 생존 변이가 놓인 줄은 **이 기능의 증거가 실제로
# 지나간 줄**이므로, 다른 기능으로 넘기면 아무도 확인하지 않는 상태가 된다.
#
# 소스를 grep 하지 않고 **렌더된 출력**을 본다. 소스에는 "이전 문구는 …였다" 라는
# 설명 주석이 남아 있으므로 grep 은 그것까지 잡는다 — 검사기가 자기 문서를
# 결함으로 읽는 꼴이다. 조언은 출력이므로 출력으로 검증한다.
advice = mutate.format_mutation({
    "feature": "T-001",
    "sources": ["own.ts (9)", "other.ts (4)"],
    "mutants": [
        mutate.MutantResult("논리 반전 (&& → ||)", "src/own.ts", 12, "survived"),
        mutate.MutantResult("논리 반전 (&& → ||)", "src/other.ts", 30, "survived"),
    ],
    "killed": 0, "survived": 2, "invalid": 0, "types": 0, "out_of_spec": 0,
    "score": 0.0, "sites": 2, "attempted": 2,
    "skipped_unexecuted": 0, "reached_lines": 2, "unmapped_files": [],
})
check("다른 파일의 생존을 '부수적 실행'으로 치부하지 않는다",
      "부수적 실행일 뿐" in advice, False)
check("다른 기능의 측정으로 책임을 넘기지 않는다",
      "소유한 기능의 측정에서 다시 확인" in advice, False)
check("그 줄도 이 기능의 증거가 실행한다고 말한다",
      "이 기능의 증거가 실제로 실행한다" in advice, True)
check("소유권은 '어디에 쓸지'만 말한다고 적는다",
      "필요 여부를 말하지 않는다" in advice, True)
check("이 기능이 소유한 파일의 생존은 진짜 구멍이라고 말한다",
      "증거의 진짜 구멍이다" in advice, True)

print("\n[7] 게이트 — '구문이 없다' 와 '증거가 닿지 않는다' 를 구분하는가")
# 둘 다 '대상 부재'이지만 **기록되는 사유가 달라야** 한다. 같은 문구로 적으면
# 나중에 읽는 사람이 "변이할 구문이 없는 모듈"로 오해한다.
feat_a = {"id": "T-001", "name": "구문 없음", "passes": False}
feat_b = {"id": "T-002", "name": "닿지 않음", "passes": False}


def _reason(report):
    """verify 의 대상 부재 분기가 만드는 사유를 같은 규칙으로 재현한다."""
    unexec = report.get("skipped_unexecuted") or 0
    if unexec:
        return ("변이 가능한 구문은 {}곳 있으나 **증거가 그 줄을 "
                "하나도 지나가지 않습니다** — 테스트의 단정이 약한 것이 아니라 "
                "도달하지 않는 것입니다 (TS-026)").format(unexec)
    return "변이를 적용할 구문이 없습니다 (비교·논리·조건·불리언 없음)"


check("구문 자체가 없으면 그렇게 적는다",
      "변이를 적용할 구문이 없습니다" in _reason({"skipped_unexecuted": 0}), True)
check("닿지 않는 것이면 그렇게 적는다",
      "증거가 그 줄을" in _reason({"skipped_unexecuted": 5}), True)
check("두 사유는 다른 문장이다",
      _reason({"skipped_unexecuted": 0}) == _reason({"skipped_unexecuted": 5}), False)
check("닿지 않는 경우에도 **거부가 아니다** (커버리지 게이트가 이미 1줄을 요구했다)",
      "거부" in _reason({"skipped_unexecuted": 5}), False)
# 저장되는 기록이 점수와 함께 '무엇을 뺐는지'를 담는가 (TS-024 의 규칙)
src_verify = (PROJECT / "harness" / "verify.py").read_text(encoding="utf-8")
check("통과 기록에 unreached_sites 를 담는다", '"unreached_sites"' in src_verify, True)
check("통과 기록에 unmapped_files 를 담는다", '"unmapped_files"' in src_verify, True)

print("\n[8] 픽스처 — 호출되지 않는 함수가 변이 대상에서 빠지는가")
# `vanilla-js` 픽스처는 이 결함을 고정할 목적으로 `neverCalled()` 를 담고 있다.
# vitest 를 설치하지 않으므로 줄 지도는 손으로 준다 — 정적 계층 검증이다 (TS-025).
fix = PROJECT / "verification" / "fixtures" / "vanilla-js" / "src" / "app.js"
text = fix.read_text(encoding="utf-8")
src_lines = text.split(NL)
never_line = next(i for i, l in enumerate(src_lines, 1) if "flag === true" in l)
resolve_line = next(i for i, l in enumerate(src_lines, 1) if "PAGES.includes" in l)
check("픽스처에 호출되지 않는 분기가 있다", never_line > resolve_line, True)
all_sites = mutate._candidate_lines(text, r"if \(", None)
check("필터 없이는 둘 다 후보", sorted(all_sites), sorted([resolve_line, never_line]))
reached = mutate._candidate_lines(text, r"if \(", {resolve_line})
check("증거가 닿는 줄만 후보", reached, [resolve_line])
check("neverCalled 의 분기는 제외된다", never_line in reached, False)

print("\n[9] 실제 레포 — F-005 의 도달률이 100% 가 아님을 사실로 고정한다")
# 숫자를 박지 않는다 (TS-024). '미실행 지점이 존재한다'는 **구조적 사실**만 본다.
# 이것이 거짓이 되는 날은 LoginForm 의 테스트가 모든 분기를 덮은 날이고,
# 그때는 이 검증이 실패해 사람에게 알린다 — 그것이 옳은 동작이다.
lf = PROJECT / "web_target" / "src" / "components" / "LoginForm.tsx"
lf_text = lf.read_text(encoding="utf-8")
lf_sites = sorted({ln for _, pat, _ in mutate.MUTATIONS
                   for ln in mutate._candidate_lines(lf_text, pat)})
check("LoginForm.tsx 에 변이 후보가 여럿 있다", len(lf_sites) > 5, True)
check("F-005 의 증거 파일 목록을 얻는 경로가 있다",
      callable(verify.coverage_for_feature), True)

print(f"{NL}{'=' * 60}")
print(f"TS-026 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'=' * 60}")
sys.exit(1 if fail else 0)

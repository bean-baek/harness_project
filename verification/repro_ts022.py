"""
TS-022 검증 스크립트 — 탐지 범위 확대
─────────────────────────────────────
세 가지를 검증한다.

  1) **표본 편향 제거** — 이전 구현은 규칙당 `lines[0]` 만 썼다. `LoginForm.tsx` 는
     변이 가능 지점 19곳이 **전부 실행되는 줄**인데 3곳만 시도됐고, 32번 줄이 항상
     이기므로 55·56번 줄(`safeRedirectTarget` 의 오픈 리다이렉트 가드 = TS-011 의 수정)은
     **한 번도 검사되지 않았다.**

  2) **컬렉션 멤버 제거 연산자** — `routes.ts` 는 증거가 6줄 실행하는데 변이 지점이
     0곳이었다(배열에는 비교·논리·조건이 없다). 실험 결과 보호 경로 4개 중 **3개를
     지워도 전체 스위트가 통과**했다 (51 → 49 통과, 실패 0). 기존 사다리 네 칸이
     전부 통과하는 동안 명세가 요구하는 보호가 사라진다.

  3) **`types` 상태** — 구문이 구성상 유효한 변이에서 tsc 가 실패하면 그것은
     '폐기'가 아니라 **타입 수준의 결함 감지**다. 증거 점수의 분자에는 넣지 않되
     (잡은 것은 테스트가 아니다) 구조적 보호가 있다는 사실은 따로 센다.

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


def tmp():
    return Path(tempfile.mkdtemp(prefix="ts022-"))


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


print("\n[1] select_spread — 항상 같은 곳을 고르지 않는가")
s = mutate.select_spread
c19 = list(range(19))
check("예산 1", s(c19, 1), [0])
check("예산 3 — 처음·중간·끝", s(c19, 3), [0, 9, 18])
check("예산 6 — 고르게", s(c19, 6), [0, 4, 7, 11, 14, 18])
check("예산이 후보보다 크면 전수", s([1, 2, 3], 10), [1, 2, 3])
check("예산 0 은 빈 목록", s(c19, 0), [])
check("후보가 없으면 빈 목록", s([], 5), [])
check("결정론적 — 두 번 호출해도 같다", s(c19, 6), s(c19, 6))
# 핵심: 첫 번째만 고르지 않는다
check("예산 3 이 마지막 후보를 포함한다 (앞머리 편향 없음)", 18 in s(c19, 3), True)
check("중복을 만들지 않는다", len(set(s(c19, 7))), 7)
# round 가 같은 인덱스를 두 번 고를 수 있는 경계
check("작은 후보 + 큰 예산도 중복 없음", len(set(s([0, 1, 2, 3], 3))), 3)

print("\n[2] 실제 편향 재현 — 예산 3 으로도 오픈 리다이렉트 가드에 닿는가")
src = (PROJECT / "web_target" / "src" / "components" / "LoginForm.tsx")
text = src.read_text(encoding="utf-8")
candidates = sorted(
    (lineno, rule)
    for rule, pattern, repl in mutate.MUTATIONS
    for lineno in mutate._candidate_lines(text, pattern)
)
check("LoginForm 의 변이 후보가 10곳 이상", len(candidates) >= 10, True)
old_way = []                                  # 이전 구현: 규칙당 lines[0], 최대 3
for rule, pattern, repl in mutate.MUTATIONS:
    lines = mutate._candidate_lines(text, pattern)
    if lines:
        old_way.append(lines[0])
    if len(old_way) >= 3:
        break
new_way = [ln for ln, _ in mutate.select_spread(candidates, 3)]
print(f"        이전 방식 3곳: {sorted(set(old_way))}")
print(f"        새 방식   3곳: {sorted(set(new_way))}")
check("새 방식은 파일 뒷부분에도 닿는다", max(new_way) > max(old_way), True)
guards = [ln for ln, _ in candidates if 50 <= ln <= 60]
check("safeRedirectTarget 구간(50~60줄)에 후보가 있다", len(guards) >= 1, True)
check("이전 방식은 그 구간에 닿지 못했다",
      any(50 <= ln <= 60 for ln in old_way), False)
wide = [ln for ln, _ in mutate.select_spread(candidates, 8)]
check("예산 8 이면 그 구간에 닿는다", any(50 <= ln <= 60 for ln in wide), True)

print("\n[3] drop_member — 선언 범위 안에서만 지우는가")
d = mutate.drop_member
one_line = "export const P = ['/', '/dashboard', '/profile', '/settings'] as const;"
check("첫 멤버", d(one_line, "P", "/"),
      "export const P = [ '/dashboard', '/profile', '/settings'] as const;")
check("중간 멤버", d(one_line, "P", "/dashboard"),
      "export const P = ['/', '/profile', '/settings'] as const;")
check("마지막 멤버 — 쉼표가 남지 않는다", d(one_line, "P", "/settings"),
      "export const P = ['/', '/dashboard', '/profile'] as const;")
check("배열이 여전히 유효 (쉼표 균형)",
      d(one_line, "P", "/settings").count(",") , one_line.count(",") - 1)
check("없는 멤버는 None", d(one_line, "P", "/nope"), None)
check("없는 컬렉션은 None", d(one_line, "Q", "/"), None)

multi = NL.join([
    "export const PATHS = [",
    "  '/a',",
    "  '/b',",
    "  '/c',",
    "] as const;",
])
got = d(multi, "PATHS", "/b")
check("여러 줄 배열", "'/b'" in (got or ""), False)
check("여러 줄 — 나머지는 유지", "'/a'" in got and "'/c'" in got, True)

# 선언 밖의 같은 문자열은 건드리지 않는다
with_dupe = NL.join([
    "// 경로 목록: '/a' 를 포함한다",
    "export const PATHS = ['/a', '/b'];",
    "const other = '/a';",
])
got = d(with_dupe, "PATHS", "/a")
check("주석의 동일 문자열은 보존", "// 경로 목록: '/a'" in got, True)
check("선언 밖 변수의 동일 문자열도 보존", "const other = '/a';" in got, True)
check("선언 안에서만 제거", "['/b']" in got.replace(" ", ""), True)

print("\n[4] _member_line — 주석의 경로에 속지 않는가")
ml = mutate._member_line
real = (PROJECT / "web_target" / "src" / "routes.ts").read_text(encoding="utf-8")
line_slash = ml(real, "PROTECTED_PATHS", "/")
check("routes.ts 의 '/' 는 1번 줄이 아니다 (주석 경로 오매칭 방어)",
      line_slash > 1, True)
check("선언 범위 안의 줄을 가리킨다",
      "'/'" in real.split(NL)[line_slash - 1] or '"/"' in real.split(NL)[line_slash - 1],
      True)
check("모르는 컬렉션은 0", ml(real, "NOPE", "/"), 0)

print("\n[5] collection_candidates — 증거가 실행하는 파일만")
r = tmp()
write(r / "src" / "routes.ts", "export const PATHS = ['/a', '/b', '/c'];")
write(r / "src" / "other.ts", "export const ROLES = ['admin', 'user'];")
write(r / ".harness.json", json.dumps({
    "target": ".", "runner": "jest", "source_dirs": ["src"],
    "unit_suffixes": [".test.ts"], "e2e_suffixes": [".spec.ts"],
}))
from harness import project as project_mod

project_mod.clear_cache()
cands = mutate.collection_candidates(str(r), ["routes.ts"])
check("커버된 파일의 컬렉션만", sorted({c[0] for c in cands}), ["PATHS"])
check("멤버마다 후보 하나", len(cands), 3)
check("커버 안 된 파일의 컬렉션은 제외",
      any(c[0] == "ROLES" for c in cands), False)
cands_both = mutate.collection_candidates(str(r), ["routes.ts", "other.ts"])
check("둘 다 커버되면 둘 다", sorted({c[0] for c in cands_both}), ["PATHS", "ROLES"])
project_mod.clear_cache()

print("\n[6] types 상태 — 타입이 잡은 것을 '폐기'로 묻지 않는가")
work = tmp()
write(work / "src" / "routes.ts", "export const PATHS = ['/a', '/b', '/c'];")
write(work / "features.json", "[]")
write(work / ".harness.json", json.dumps({
    "target": ".", "runner": "jest", "source_dirs": ["src"],
    "unit_suffixes": [".test.ts"], "e2e_suffixes": [".spec.ts"],
}))
project_mod.clear_cache()

orig = (mutate.tagged_test_files, mutate.coverage_for_feature,
        mutate._typechecks, mutate._tests_fail)
try:
    mutate.tagged_test_files = lambda pr, fid: ["src/x.test.ts"]
    mutate.coverage_for_feature = lambda pr, fid, top_n=5, test_files=None: (
        {"covered_statements": 3, "files_touched": 1, "sources": ["routes.ts (3)"]}, "")

    # 6-A 전부 통과 → 생존 (tsc 호출 없음)
    tsc_calls: list[int] = []
    mutate._typechecks = lambda pr: (tsc_calls.append(1), True)[1]
    mutate._tests_fail = lambda pr, f, t: False
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("컬렉션 변이가 생성된다", rep["attempted"], 3)
    check("전부 생존", rep["survived"], 3)
    check("생존이면 tsc 호출 0회", len(tsc_calls), 0)
    check("사유에 '덜 돌 뿐' 설명", any("덜 돌 뿐" in m.detail for m in rep["mutants"]), True)

    # 6-B 테스트 실패 + 타입 통과 → 잡음
    mutate._tests_fail = lambda pr, f, t: True
    mutate._typechecks = lambda pr: True
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("테스트가 잡으면 killed", rep["killed"], 3)
    check("types 는 0", rep["types"], 0)
    check("점수 100%", rep["score"], 1.0)

    # 6-C 테스트 실패 + 타입 실패 → **types** (폐기 아님)
    mutate._typechecks = lambda pr: False
    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("타입이 잡으면 types", rep["types"], 3)
    check("폐기(invalid) 로 세지 않는다", rep["invalid"], 0)
    check("증거 점수의 분자에 넣지 않는다", rep["killed"], 0)
    check("점수는 None (유효한 테스트 판정이 없다)", rep["score"], None)
    check("사유가 '타입 검사가 잡았다'",
          any("타입 검사" in m.detail for m in rep["mutants"]), True)

    # 6-D 표본 크기를 보고하는가
    check("sites 가 후보 총수", rep["sites"], 3)
    check("attempted 가 시도 수", rep["attempted"], 3)
    text = mutate.format_mutation(rep)
    check("보고에 표본 크기", "후보 3곳 중 3곳 시도" in text, True)
    check("전수면 '(전수)' 표시", "(전수)" in text, True)
    check("타입잡음을 출력", "타입이 잡음" in text, True)

    # 6-E 예산으로 건너뛰면 그 사실을 보고하는가
    rep2 = mutate.mutate_feature(str(work), "C-001", max_files=1, max_collection=1)
    check("예산 1 이면 1건만 시도", rep2["attempted"], 1)
    check("후보 총수는 그대로", rep2["sites"], 3)
    check("건너뛴 수를 보고", "2곳 건너뜀" in mutate.format_mutation(rep2), True)
    check("늘리는 방법을 안내", "--max-per-file" in mutate.format_mutation(rep2), True)

    # 6-F 원본 복원
    check("원본 복원",
          (work / "src" / "routes.ts").read_text(encoding="utf-8"),
          "export const PATHS = ['/a', '/b', '/c'];")
finally:
    (mutate.tagged_test_files, mutate.coverage_for_feature,
     mutate._typechecks, mutate._tests_fail) = orig
    project_mod.clear_cache()

print("\n[7] 실제 레포 — 컬렉션 연산자가 대상 앱에 적용되는가")
real_cands = mutate.collection_candidates(
    "web_target", ["routes.ts", "ProtectedRoute.tsx", "LoginForm.tsx"])
check("PROTECTED_PATHS 후보 생성", sorted({c[0] for c in real_cands}), ["PROTECTED_PATHS"])
check("멤버 4개 전부 후보", len(real_cands), 4)
members = sorted(c[2] for c in real_cands)
check("멤버 목록", members, ["/", "/dashboard", "/profile", "/settings"])
# 실제 파일에 적용해 배열이 유효하게 남는지 (쓰지는 않는다)
for _, declared_in, member in real_cands:
    mutated = mutate.drop_member(real, "PROTECTED_PATHS", member)
    check(f"{member!r} 제거가 유효한 배열을 만든다",
          mutated is not None and mutated.count("[") == real.count("[")
          and mutated.count("]") == real.count("]"), True)
check("원본은 변경되지 않았다",
      (PROJECT / "web_target" / "src" / "routes.ts").read_text(encoding="utf-8"), real)

print("\n[8] CLI 예산 플래그 — 도움말의 기본값이 실제 상수와 일치하는가")
from harness import cli as cli_mod

# cli 는 harness.mutate 를 지연 임포트하므로 도움말용 기본값을 복제해 둔다.
# 복제는 어긋날 수 있으므로 여기서 고정한다 — 죽은 설정의 변종을 막는다 (TS-019 의 교훈).
check("per-file 기본값 일치", cli_mod.MUT_PER_FILE_DEFAULT, mutate.MAX_MUTANTS_PER_FILE)
check("collection 기본값 일치", cli_mod.MUT_COLLECTION_DEFAULT,
      mutate.MAX_COLLECTION_MUTANTS)
args = cli_mod.build_parser().parse_args(
    ["mutate", "F-005", "--max-per-file", "8", "--max-collection", "2"])
check("--max-per-file 를 받는다", args.max_per_file, 8)
check("--max-collection 를 받는다", args.max_collection, 2)
args2 = cli_mod.build_parser().parse_args(["mutate", "F-005"])
check("지정하지 않으면 None (모듈 기본값 사용)",
      (args2.max_per_file, args2.max_collection), (None, None))

print(f"\n{'='*60}")
print(f"TS-022 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

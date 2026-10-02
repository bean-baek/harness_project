"""
TS-023 검증 스크립트 — 생존의 의미를 명세로 가린다
──────────────────────────────────────────────────
TS-022 가 컬렉션 멤버 제거를 주입했고 `PROTECTED_PATHS` 의 `/`, `/profile`,
`/settings` 가 생존했다. 그래서 "테스트가 약하다"고 읽고 단정을 추가하려 했다.

**그것이 틀렸다.** F-005 의 명세는 `/dashboard` 만 지목한다. 나머지 3개를 테스트로
고정하면 **명세에 없는 것을 단정하는 테스트**가 되고, 그것은 TS-014 가
'측정 도구 오류'로 분류해 고쳤던 바로 그 패턴이다.

생존은 두 종류다 — 그 구분을 **사실로** 판정한다:
  명세가 멤버를 지목함  → 증거의 진짜 공백 (요구되는데 고정되지 않았다)
  명세에 없음           → **명세의 공백** (앱이 명세를 넘어 구현했다)

검증 항목:
  1) `spec_text` — 설명 + 단계를 모아 읽는가
  2) `spec_names` — 경로 경계 판정이 정확한가 (한글 뒤따름·부분 문자열 함정)
  3) 분류 — 명세 밖 생존이 점수 분모에서 빠지는가
  4) 보고 — 두 종류를 섞지 않고 각각의 조치를 안내하는가
  5) 실제 레포 — F-005 의 명세가 지목하는 것은 `/dashboard` 하나뿐인가

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
    return Path(tempfile.mkdtemp(prefix="ts023-"))


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


print("\n[1] spec_text — 설명과 단계를 모아 읽는가")
r = tmp()
write(r / "features.json", json.dumps([
    {"id": "C-001", "description": "보호 경로 접근 차단",
     "steps": ["/dashboard 에 접속한다", "/login 으로 이동한다"], "passes": False},
], ensure_ascii=False))
spec = mutate.spec_text(str(r), "C-001")
check("설명 포함", "보호 경로 접근 차단" in spec, True)
check("단계 전부 포함", "/dashboard" in spec and "/login" in spec, True)
check("없는 기능은 빈 문자열", mutate.spec_text(str(r), "C-999"), "")
check("명세 파일이 없으면 빈 문자열", mutate.spec_text(str(tmp()), "C-001"), "")

print("\n[2] spec_names — 경로 경계 판정")
s = "로그인하지 않은 상태에서 /dashboard에 접속한다 /login 페이지로 이동 (?redirect=/dashboard)"
check("명세가 지목한 경로", mutate.spec_names("/dashboard", s), True)
check("명세가 지목한 다른 경로", mutate.spec_names("/login", s), True)
check("명세에 없는 경로", mutate.spec_names("/profile", s), False)
check("명세에 없는 경로 2", mutate.spec_names("/settings", s), False)
# 핵심 함정: 짧은 멤버가 다른 경로의 접두사로 오매칭되면 전부 '명세에 있음'이 된다
check("'/' 가 '/dashboard' 에 오매칭되지 않는다", mutate.spec_names("/", s), False)
check("'/' 가 '?redirect=/x' 에도 오매칭되지 않는다",
      mutate.spec_names("/", "?redirect=/dashboard"), False)
check("'/' 가 단독으로 쓰이면 인정", mutate.spec_names("/", "루트 / 에 접근한다"), True)
# 한글이 뒤따르는 경우 — \w 를 쓰면 한글이 단어 문자라 전부 미매칭된다 (실측된 함정)
check("경로 뒤 한글은 경계로 인정", mutate.spec_names("/dashboard", "/dashboard에 접속"), True)
check("경로 뒤 공백도 경계", mutate.spec_names("/dashboard", "/dashboard 에 접속"), True)
check("더 긴 경로의 접두사는 미매칭",
      mutate.spec_names("/dash", "/dashboard 에 접속"), False)
check("하이픈 경로도 구분", mutate.spec_names("/a", "/a-b 로 이동"), False)
check("빈 멤버는 False", mutate.spec_names("", s), False)
check("빈 명세는 False", mutate.spec_names("/dashboard", ""), False)

print("\n[3] 분류 — 명세 밖 생존이 분모에서 빠지는가")
work = tmp()
write(work / "src" / "routes.ts",
      "export const PATHS = ['/spec', '/extra', '/other'];")
write(work / "features.json", json.dumps([
    {"id": "C-001", "description": "보호", "steps": ["/spec 에 접근하면 차단된다"],
     "passes": False},
], ensure_ascii=False))
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
    mutate._typechecks = lambda pr: True
    mutate._tests_fail = lambda pr, f, t: False       # 전부 생존

    rep = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("멤버 3개 전부 시도", rep["attempted"], 3)
    check("명세가 지목한 1건만 'survived'", rep["survived"], 1)
    check("명세 밖 2건은 'out-of-spec'", rep["out_of_spec"], 2)
    check("점수 분모는 명세 안 생존만 (0/1)", rep["score"], 0.0)
    oos = [m for m in rep["mutants"] if m.status == "out-of-spec"]
    check("명세 밖 멤버 식별", sorted(m.rule.split("← ")[1].rstrip(")") for m in oos),
          ["'/extra'", "'/other'"])
    surv = [m for m in rep["mutants"] if m.status == "survived"]
    check("명세 안 멤버 식별", surv[0].rule.split("← ")[1].rstrip(")"), "'/spec'")
    check("명세 안 생존은 '진짜 공백'으로 설명", "진짜 공백" in surv[0].detail, True)
    check("명세 밖 생존은 '명세의 공백'으로 설명", "명세의 공백" in oos[0].detail, True)
    check("명세 밖 생존은 TS-014 를 인용", "TS-014" in oos[0].detail, True)

    # 테스트가 잡으면 명세와 무관하게 killed
    mutate._tests_fail = lambda pr, f, t: True
    rep2 = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("테스트가 잡으면 명세와 무관하게 killed", rep2["killed"], 3)
    check("그때는 out-of-spec 0", rep2["out_of_spec"], 0)
    check("점수 100%", rep2["score"], 1.0)

    # 명세가 비어 있으면 전부 '명세 밖' — 추측하지 않는다
    write(work / "features.json", json.dumps([
        {"id": "C-001", "description": "", "steps": [], "passes": False},
    ], ensure_ascii=False))
    mutate._tests_fail = lambda pr, f, t: False
    rep3 = mutate.mutate_feature(str(work), "C-001", max_files=1)
    check("명세가 비면 전부 명세 밖 (요구의 근거가 없다)", rep3["out_of_spec"], 3)
    check("그때 진짜 공백은 0", rep3["survived"], 0)
    check("점수는 None (판정할 유효 표본이 없다)", rep3["score"], None)
finally:
    (mutate.tagged_test_files, mutate.coverage_for_feature,
     mutate._typechecks, mutate._tests_fail) = orig
    project_mod.clear_cache()

print("\n[4] 보고 — 두 종류를 섞지 않는가")
rep = {
    "feature": "C-001", "sources": ["routes.ts (3)"], "mutants": [
        mutate.MutantResult("컬렉션 멤버 제거 (P ← '/spec')", "src/routes.ts", 1,
                            "survived", "명세가 이 경로를 지목한다 — 증거의 진짜 공백이다"),
        mutate.MutantResult("컬렉션 멤버 제거 (P ← '/extra')", "src/routes.ts", 1,
                            "out-of-spec", "명세가 이 멤버를 요구하지 않는다"),
        mutate.MutantResult("컬렉션 멤버 제거 (P ← '/typed')", "src/routes.ts", 1,
                            "types", "타입 검사가 잡았다"),
    ],
    "killed": 0, "survived": 1, "invalid": 0, "types": 1, "out_of_spec": 1,
    "score": 0.0, "sites": 3, "attempted": 3,
}
text = mutate.format_mutation(rep)
check("요약에 명세 범위 밖 집계", "명세 범위 밖 1" in text, True)
check("요약에 타입이 잡음 집계", "타입이 잡음 1" in text, True)
check("명세 밖 전용 안내 블록", "명세의 공백**이다" in text, True)
check("안내가 '먼저 명세에 적는다' 로 끝난다", "먼저 명세에 적는다" in text, True)
check("타입 전용 안내 블록", "컴파일러가 막았다" in text, True)
check("타입은 '폐기로 묻지 않는다' 고 명시", "'폐기'로 묻지 않는다" in text, True)
check("상태별 표기", "명세밖" in text and "타입잡음" in text, True)
# 진짜 공백과 명세 밖을 같은 문단에 섞지 않는다
idx_warn = text.index("⚠ 생존")
idx_oos = text.index("◆ 명세 범위 밖")
check("진짜 공백 경고가 명세 밖 안내보다 앞에 온다", idx_warn < idx_oos, True)

print("\n[5] 실제 레포 — F-005 의 명세가 지목하는 경로")
real_spec = mutate.spec_text("web_target", "F-005")
check("명세를 읽었다", len(real_spec) > 20, True)
members = ["/", "/dashboard", "/profile", "/settings"]
named = {m: mutate.spec_names(m, real_spec) for m in members}
for m in members:
    print(f"        {m:<12} → {'명세에 있음' if named[m] else '명세에 없음'}")
check("명세가 지목하는 것은 /dashboard 하나뿐", [m for m in members if named[m]],
      ["/dashboard"])
check("나머지 3개는 명세 밖", sum(1 for m in members if not named[m]), 3)
# 그래서 그 3개에 단정을 추가하는 것은 TS-014 의 패턴이 된다
check("명세에 '/profile' 이 없다는 사실 고정", mutate.spec_names("/profile", real_spec), False)

print(f"\n{'='*60}")
print(f"TS-023 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

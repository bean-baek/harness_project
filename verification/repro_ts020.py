"""
TS-020 검증 스크립트 — 증거 독립성
──────────────────────────────────
**테스트가 검증 대상의 구조를 자기가 공급하는지** 판정하는 검사기를 검증한다.

TS-016 의 교훈대로 **검사기 자신이 작동하는지 먼저 묻는다.**
결함을 심은 임시 프로젝트를 주고 잡는지 확인한 뒤, 실제 레포 수치를 단정한다.

검증 대상 (전부 사실 판정 — import 했는가 / 멤버 리터럴이 몇 개인가):
  1) 앱의 단일 출처 컬렉션 수집
  2) 자급 판정 — import 하면 제외, 멤버를 적으면 포착
  3) 심각도 분리 — enumerated(2개 이상, 컬렉션 재현) vs hard-coded(1개, 기대값 단정)
  4) 등급 — 채널 수와 자급을 **합치지 않고** 조합한다
  5) 실제 레포: TS-013 의 그 파일을 하드코딩 없이 지목하는가
  6) CLI 는 보고만 한다 (종료 코드 0)

런너를 실행하지 않는다. 전부 정적 분석이다.
"""
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import independence as ind
from harness.project import ProjectConfig

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
    return Path(tempfile.mkdtemp(prefix="ts020-"))


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CFG = ProjectConfig(source_dirs=["src"], unit_suffixes=[".test.tsx"],
                    e2e_suffixes=[".spec.ts"])


print("\n[1] 단일 출처 컬렉션 수집")
r = tmp()
write(r / "src" / "routes.ts", NL.join([
    "export const PROTECTED_PATHS = ['/', '/dashboard', '/profile'] as const;",
    "export const ROLES = ['admin', 'user'];",
    "const lowercase = ['a', 'b'];",          # 소문자 — 선언으로 보지 않는다
    "export const SINGLE = ['only'];",        # 1개 — 컬렉션이 아니다
]))
write(r / "src" / "x.test.tsx", "export const DECOY = ['p','q'];")  # 테스트는 안 본다
colls = {c.name: c for c in ind.declared_collections(r, CFG)}
check("대문자 + 멤버 2개 이상을 수집", sorted(colls), ["PROTECTED_PATHS", "ROLES"])
check("멤버를 보존", colls["PROTECTED_PATHS"].members, ["/", "/dashboard", "/profile"])
check("선언 위치를 기록", colls["PROTECTED_PATHS"].declared_in, "src/routes.ts")
check("소문자 배열은 선언이 아니다", "lowercase" in colls, False)
check("멤버 1개는 컬렉션이 아니다", "SINGLE" in colls, False)
check("테스트 파일의 배열은 앱 선언이 아니다", "DECOY" in colls, False)

print("\n[2] 자급 판정 — import 하면 제외, 멤버를 적으면 포착")
collections = list(colls.values())

# 2-A import 하고 순회한다 → 독립 (AppRoutes.test.tsx 의 모양)
write(r / "src" / "good.test.tsx", NL.join([
    "import { PROTECTED_PATHS } from './routes';",
    "test.each(PROTECTED_PATHS)('protects %s', (p) => {});",
    "expect(PROTECTED_PATHS).toContain('/dashboard');",   # 리터럴이 있어도 import 했다
]))
found = ind.self_supplied_in(r / "src" / "good.test.tsx", r, collections)
check("import 하면 리터럴이 있어도 자급 아님", [f.collection for f in found], [])

# 2-B import 없이 멤버를 적는다 → 자급 (ProtectedRoute.test.tsx 의 모양)
write(r / "src" / "bad.test.tsx", NL.join([
    "import { Guard } from './Guard';",
    "<Route path='/dashboard' element={<Guard/>} />",
    "<Route path='/' element={<Home/>} />",
]))
found = ind.self_supplied_in(r / "src" / "bad.test.tsx", r, collections)
check("import 없이 멤버를 적으면 자급", [f.collection for f in found], ["PROTECTED_PATHS"])
check("어떤 멤버인지 지목", found[0].literals, ["/", "/dashboard"])
check("선언 위치를 함께 보고", found[0].declared_in, "src/routes.ts")

# 2-C 네임스페이스 import 도 인정
write(r / "src" / "ns.test.tsx", NL.join([
    "import * as routes from './routes';",
    "routes.PROTECTED_PATHS.forEach((p) => {});",
    "const x = '/dashboard';",
]))
found = ind.self_supplied_in(r / "src" / "ns.test.tsx", r, collections)
check("네임스페이스 import 도 '앱의 선언을 읽는다'", found, [])

# 2-D 컬렉션과 무관한 리터럴은 잡지 않는다
write(r / "src" / "unrelated.test.tsx", "const x = '/login'; const y = 'hello';")
found = ind.self_supplied_in(r / "src" / "unrelated.test.tsx", r, collections)
check("멤버가 아닌 리터럴은 무관", found, [])

print("\n[3] 심각도 분리 — 섞으면 신호가 죽는다")
two = ind.SelfSupplied("P", "src/routes.ts", "a.test.tsx", ["/", "/dashboard"])
one = ind.SelfSupplied("P", "src/routes.ts", "b.test.tsx", ["/profile"])
check("멤버 2개 = 컬렉션 재현", two.severity, "enumerated")
check("멤버 1개 = 기대값 단정", one.severity, "hard-coded")
check("재현은 '열거'로 설명", "열거" in two.line(), True)
check("단정은 '약한 결합'으로 설명", "약한 결합" in one.line(), True)
# 실측 대비: toHaveBeenCalledWith('/profile') 는 구조를 공급하지 않는다
write(r / "src" / "assert.test.tsx", NL.join([
    "import { Menu } from './Menu';",
    "expect(mockNavigate).toHaveBeenCalledWith('/profile');",
]))
found = ind.self_supplied_in(r / "src" / "assert.test.tsx", r, collections)
check("기대값 단정 1건은 hard-coded", [f.severity for f in found], ["hard-coded"])

print("\n[4] 등급 — 채널 수와 자급을 합치지 않는다")
no_ev = ind.FeatureIndependence("F-001")
check("증거 없음", no_ev.grade, "no-evidence")

single = ind.FeatureIndependence("F-002", unit_files=["a.test.tsx"])
check("단위만 = 단일채널", single.grade, "single-channel")
check("사유가 '하나뿐'을 말한다", "하나뿐" in single.reason(), True)

both = ind.FeatureIndependence("F-003", unit_files=["a.test.tsx"], e2e_files=["b.spec.ts"])
check("두 채널 = 교차검증", both.grade, "cross-checked")

ts013 = ind.FeatureIndependence("F-004", unit_files=["a.test.tsx"], self_supplied=[two])
check("컬렉션 재현 + 단일채널 = 자급 (TS-013 의 모양)", ts013.grade, "self-supplied")
check("사유가 TS-013 을 인용", "TS-013" in ts013.reason(), True)

mitigated = ind.FeatureIndependence("F-005", unit_files=["a.test.tsx"],
                                    e2e_files=["b.spec.ts"], self_supplied=[two])
check("컬렉션 재현이지만 E2E 가 있으면 등급을 내리지 않는다",
      mitigated.grade, "cross-checked")
check("그래도 사유에 자급을 명시", "손으로 재현" in mitigated.reason(), True)

weak = ind.FeatureIndependence("F-006", unit_files=["a.test.tsx"], self_supplied=[one])
check("약한 결합만 있으면 등급을 내리지 않는다 (단일채널 유지)",
      weak.grade, "single-channel")
check("enumerated 만 등급을 끌어내린다", len(weak.enumerated), 0)
check("hard_coded 는 따로 센다", len(weak.hard_coded), 1)

print("\n[5] 실제 레포 — 하드코딩 없이 TS-013 의 파일을 지목하는가")
from harness.verify import load_features

feats = load_features("web_target")
real_colls = ind.declared_collections("web_target")
results = ind.audit_independence("web_target", feats)
by_id = {r.feature_id: r for r in results}

check("PROTECTED_PATHS 를 단일 출처로 인식",
      [c.name for c in real_colls], ["PROTECTED_PATHS"])
check("통과 기능 전수를 분석", len(results), sum(1 for f in feats if f.get("passes")))

f005 = by_id["F-005"]
enum_files = [s.test_file for s in f005.enumerated]
check("F-005 에서 TS-013 의 그 파일을 지목",
      any("ProtectedRoute.test.tsx" in f for f in enum_files), True)
check("그 파일이 열거한 멤버를 보고",
      sorted(f005.enumerated[0].literals), ["/", "/dashboard"])
check("F-005 는 E2E 가 있어 등급이 교차검증", f005.grade, "cross-checked")
check("AppRoutes.test.tsx 는 import 하므로 자급에 없다",
      any("AppRoutes" in s.test_file for s in f005.self_supplied), False)

f018 = by_id["F-018"]
check("F-018 은 E2E 가 0건", len(f018.e2e_files), 0)
check("F-018 등급 = 단일채널", f018.grade, "single-channel")

grades = {}
for r in results:
    grades[r.grade] = grades.get(r.grade, 0) + 1
check("등급 분포 (교차검증 5 / 단일채널 1)",
      (grades.get("cross-checked"), grades.get("single-channel")), (5, 1))
check("자급 등급 0건 — 전부 교차 채널이 있다", grades.get("self-supplied", 0), 0)
total_enum = sum(len(r.enumerated) for r in results)
total_hard = sum(len(r.hard_coded) for r in results)
check("컬렉션 재현 1건", total_enum, 1)
check("약한 결합 1건", total_hard, 1)

print("\n[6] 보고 전용 — 판정으로 차단하지 않는다")
text = ind.format_independence(results, real_colls)
check("컬렉션을 출력", "PROTECTED_PATHS" in text, True)
check("심각도별 집계를 출력", "enumerated" in text and "hard-coded" in text, True)
check("임계값을 두지 않은 이유를 명시", "근거 없는 상수" in text, True)
check("자급이 곧 결함이 아니라고 명시", "결함이 아니다" in text, True)

from harness.cli import build_parser

args = build_parser().parse_args(["independence", "--project", "web_target"])
check("CLI 서브명령 존재", args.func.__name__, "cmd_independence")
check("--project 를 받는다", args.project, "web_target")

print("\n[7] 컬렉션이 없는 프로젝트 — 조용히 넘어가는가")
bare = tmp()
write(bare / "src" / "a.ts", "export const x = 1;")
write(bare / "features.json", '[{"id":"F-001","passes":true,"description":"x"}]')
check("컬렉션 0개", ind.declared_collections(bare, CFG), [])
res = ind.analyze(bare, "F-001", CFG, [], [])
check("자급 판정 없음 (기준이 없다)", res.self_supplied, [])
check("증거도 없으므로 no-evidence", res.grade, "no-evidence")
text = ind.format_independence([res], [])
check("기준이 없다는 사실을 보고한다", "채널 수만 본다" in text, True)

print(f"\n{'='*60}")
print(f"TS-020 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

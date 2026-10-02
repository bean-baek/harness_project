"""
TS-019 검증 스크립트 — 죽은 설정·고아 코드 재발 방지
────────────────────────────────────────────────────
**이 레포가 깨끗한지**와 **검사기 자신이 작동하는지**를 둘 다 본다.

왜 둘 다 봐야 하는가 (TS-016 의 교훈):
  "감사 결과 0건"은 감사가 아무것도 못 찾는 상태와 구별되지 않는다.
  그래서 각 검사기에 **일부러 결함을 심은 임시 프로젝트**를 주고 잡는지 확인하고,
  그 다음에 실제 레포가 0건임을 단정한다. 측정 자체가 고장 났는지 먼저 묻는다.

검사 대상 (전부 '참조 0건'이라는 사실 판정 — 임계값 없음):
  1) 죽은 설정 — README 가 광고하는 환경변수인데 상수를 아무도 읽지 않는다
  2) 고아 코드 — 정의됐지만 정의 외 참조가 0건
  3) 미사용 임포트

TS-007 과 TS-019 가 같은 양식이다. 두 번 나온 것은 사람이 기억으로 막지 못한다.
"""
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import deadcode

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


def tmp(prefix="ts019-"):
    return Path(tempfile.mkdtemp(prefix=prefix))


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


NL = chr(10)

print("\n[1] 고아 탐지기가 실제로 잡는가 — 결함을 심어 확인")
r = tmp()
write(r / "mod.py", NL.join([
    "def used_elsewhere():",
    "    return 1",
    "",
    "",
    "def never_called():",
    "    return 2",
    "",
    "",
    "LIVE_CONST = 10",
    "DEAD_CONST = 20",
    "",
    "",
    "class NeverInstantiated:",
    "    pass",
    "",
]))
write(r / "caller.py", NL.join([
    "from mod import used_elsewhere, LIVE_CONST",
    "",
    "print(used_elsewhere(), LIVE_CONST)",
    "",
]))
found = {f.name for f in deadcode.find_orphans(r)}
check("호출되지 않는 함수를 잡는다", "def never_called" in found, True)
check("미사용 상수를 잡는다", "const DEAD_CONST" in found, True)
check("미사용 클래스를 잡는다", "class NeverInstantiated" in found, True)
check("다른 파일에서 쓰이는 함수는 잡지 않는다", "def used_elsewhere" in found, False)
check("다른 파일에서 쓰이는 상수는 잡지 않는다", "const LIVE_CONST" in found, False)

print("\n[2] 고아 탐지기의 오탐 방어 — 같은 파일 안의 참조")
# v1 구현이 여기서 깨졌다: CLI 명령 11개와 그래프 노드 3개가 '미사용'으로 나왔다.
r = tmp()
write(r / "app.py", NL.join([
    "def cmd_run():",
    "    return 1",
    "",
    "",
    "def register(parser):",
    "    parser.set_defaults(func=cmd_run)",
    "",
    "",
    "def node_fn():",
    "    return 2",
    "",
    "",
    "def build(graph):",
    "    graph.add_node('done', node_fn)",
    "",
    "",
    "def by_string():",
    "    return 3",
    "",
    "",
    "def dispatch(mod):",
    "    return getattr(mod, 'by_string')",
    "",
]))
found = {f.name for f in deadcode.find_orphans(r)}
check("같은 파일에서 참조되는 함수는 고아가 아니다", "def cmd_run" in found, False)
check("그래프 노드 등록(인자 전달)도 참조로 센다", "def node_fn" in found, False)
check("문자열로 참조되는 이름도 센다 (getattr)", "def by_string" in found, False)
check("register/build/dispatch 자신은 호출부가 없어 고아로 잡힌다",
      {"def register", "def build", "def dispatch"} <= found, True)

print("\n[3] 프레임워크 규약 면제")
r = tmp()
write(r / "entry.py", NL.join([
    "from __future__ import annotations",
    "",
    "",
    "def main():",
    "    return 0",
    "",
    "",
    "def __getattr__(name):",
    "    raise AttributeError(name)",
    "",
]))
found = {f.name for f in deadcode.find_orphans(r)}
check("main 은 면제", "def main" in found, False)
check("던더는 면제", "def __getattr__" in found, False)
imports = {f.name for f in deadcode.find_unused_imports(r)}
check("from __future__ import annotations 는 면제 (컴파일러 지시자)",
      "annotations" in imports, False)

print("\n[4] 미사용 임포트 탐지")
r = tmp()
write(r / "m.py", NL.join([
    "import os",
    "import sys",
    "from pathlib import Path",
    "",
    "print(os.getcwd(), Path('.'))",
    "",
]))
imports = {f.name for f in deadcode.find_unused_imports(r)}
check("쓰지 않는 임포트를 잡는다", "sys" in imports, True)
check("쓰는 임포트는 잡지 않는다 (os)", "os" in imports, False)
check("from-import 도 추적한다 (Path 사용 중)", "Path" in imports, False)

# 부분 문자열 오탐 방어 — `io` 가 'version' 안에 들어 있다고 사용으로 세면 안 된다
r = tmp()
write(r / "sub.py", NL.join([
    "import io",
    "",
    "VERSION = 'revision information'",
    "",
]))
imports = {f.name for f in deadcode.find_unused_imports(r)}
check("부분 문자열을 사용으로 오인하지 않는다 (io vs 'revision')", "io" in imports, True)

print("\n[5] 죽은 설정 탐지 — TS-007/TS-019 의 양식")
r = tmp()
write(r / "config.py", NL.join([
    "import os",
    "",
    "LIVE_SETTING = os.environ.get('APP_LIVE', '1')",
    "DEAD_SETTING = os.environ.get('APP_DEAD', '2')",
    "UNDOCUMENTED = os.environ.get('APP_SECRET', '3')",
    "PLAIN = 42",
    "",
]))
write(r / "app.py", NL.join([
    "import config",
    "",
    "print(config.LIVE_SETTING)",
    "",
]))
write(r / "README.md", NL.join([
    "| `APP_LIVE` | 1 | 살아 있는 설정 |",
    "| `APP_DEAD` | 2 | 문서는 광고하지만 코드가 안 읽는다 |",
    "",
]))
dead = {f.name: f for f in deadcode.find_dead_config(r)}
check("문서화됐지만 안 읽는 설정을 잡는다", "APP_DEAD" in dead, True)
check("읽히는 설정은 잡지 않는다", "APP_LIVE" in dead, False)
check("문서에 없는 미사용 설정은 여기서 안 잡는다 (고아 검사의 몫)",
      "APP_SECRET" in dead, False)
check("사유에 상수 이름이 담긴다", "DEAD_SETTING" in dead["APP_DEAD"].detail, True)
check("TS 번호를 인용해 맥락을 준다", "TS-007" in dead["APP_DEAD"].detail, True)
# 환경변수를 읽지 않는 평범한 상수는 죽은 설정이 아니다
check("env 를 읽지 않는 상수는 대상이 아니다",
      any(f.name == "PLAIN" for f in deadcode.find_dead_config(r)), False)

print("\n[6] 감사 범위 — 대상 앱과 가상환경은 건드리지 않는다")
r = tmp()
write(r / "keep.py", "def orphan_here():\n    pass\n")
write(r / "web_target" / "skip.py", "def orphan_skipped():\n    pass\n")
write(r / ".venv" / "lib" / "skip2.py", "def orphan_skipped2():\n    pass\n")
write(r / "node_modules" / "skip3.py", "def orphan_skipped3():\n    pass\n")
found = {f.name for f in deadcode.find_orphans(r)}
check("감사 대상 파일은 본다", "def orphan_here" in found, True)
check("web_target 은 제외 (JS 앱은 cli inspect 의 몫)", "def orphan_skipped" in found, False)
check(".venv 제외", "def orphan_skipped2" in found, False)
check("node_modules 제외", "def orphan_skipped3" in found, False)
files = [str(p) for p in deadcode.python_files(r)]
check("python_files 가 1개만 반환", len(files), 1)

print("\n[7] 이 레포가 실제로 깨끗한가")
findings = deadcode.audit(PROJECT)
by_kind: dict[str, list] = {}
for f in findings:
    by_kind.setdefault(f.kind, []).append(f)
for kind in ("dead-config", "orphan", "unused-import"):
    items = by_kind.get(kind, [])
    if items:
        for f in items[:6]:
            print(f"        발견: {f.file}:{f.line} {f.name}")
    check(f"{kind}: 0건", len(items), 0)

print("\n[8] 되살아난 손잡이 — TS-019 가 연결한 설정이 실제로 동작하는가")
import config
from harness import router

base = {"evaluation_verdict": "PASS", "iteration": 0, "max_retry": 5}
check("임계값 미달은 done 이 아니다",
      router.route_after_evaluate({**base, "evaluation_score": config.EVAL_PASS_THRESHOLD - 1}),
      "reflect")
check("임계값 이상은 done",
      router.route_after_evaluate({**base, "evaluation_score": config.EVAL_PASS_THRESHOLD}),
      "done")
# 설정을 바꾸면 판정이 실제로 바뀐다 — 이것이 '죽은 설정'이 아니라는 증거다
original = config.EVAL_PASS_THRESHOLD
try:
    config.EVAL_PASS_THRESHOLD = 50
    check("임계값을 50 으로 낮추면 60점이 통과한다",
          router.route_after_evaluate({**base, "evaluation_score": 60}), "done")
    config.EVAL_PASS_THRESHOLD = 95
    check("95 로 올리면 같은 60점이 거부된다",
          router.route_after_evaluate({**base, "evaluation_score": 60}), "reflect")
finally:
    config.EVAL_PASS_THRESHOLD = original
check("원래 값 복원", config.EVAL_PASS_THRESHOLD, original)

print("\n[9] CLI 가 감사를 노출하는가")
from harness.cli import build_parser

parser = build_parser()
args = parser.parse_args(["deadcode", "--harness-root", "."])
check("deadcode 서브명령 존재", args.func.__name__, "cmd_deadcode")
check("--harness-root 를 받는다", args.harness_root, ".")

print(f"\n{'='*60}")
print(f"TS-019 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

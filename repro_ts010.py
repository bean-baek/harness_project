"""
TS-010 검증 스크립트
────────────────────
"토큰을 쓰지 않는다"는 주장을 **증명**한다.

  1) 의존성 독립 — langchain / langgraph / dotenv / google 을 전부 차단한 상태에서
     게이트·측정·CLI 가 동작하는가. API 키 없이도 되는가.
  2) 게이트 정책 단일 구현 — CLI 와 langchain 도구가 같은 판정을 내리는가.
  3) CLI 계약 — 종료 코드(0 통과 / 1 거부 / 2 입력 오류)와 플래그 불변성.
  4) 패키지 지연 로딩 — harness.verify 임포트가 langchain 을 끌어오지 않는가.

실제 LLM 호출 없음. jest 는 가짜 JSON.
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

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


BLOCKER = '''
import sys
BLOCKED = ("langchain", "langchain_core", "langchain_google_genai",
           "langgraph", "dotenv", "google")
class Blocker:
    def find_module(self, name, path=None):
        return self if any(name == b or name.startswith(b + ".") for b in BLOCKED) else None
    def load_module(self, name):
        raise ImportError("blocked: " + name)
sys.meta_path.insert(0, Blocker())
'''


def run_isolated(code: str) -> subprocess.CompletedProcess:
    """langchain 계열을 차단하고 API 키를 비운 서브프로세스에서 코드를 실행한다."""
    script = BLOCKER + code
    import os
    env = dict(os.environ)
    env["GOOGLE_API_KEY"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, env=env,
    )


print("\n[1] 의존성 독립 — langchain/langgraph/dotenv/google 차단 상태")

r = run_isolated("import harness.verify; print('OK')")
check("harness.verify 임포트 가능", r.stdout.strip().endswith("OK"), True)

r = run_isolated("import harness.metrics; print('OK')")
check("harness.metrics 임포트 가능", r.stdout.strip().endswith("OK"), True)

r = run_isolated("import harness.cli; print('OK')")
check("harness.cli 임포트 가능", r.stdout.strip().endswith("OK"), True)

r = run_isolated("import config; print(config.REQUIRE_TEST_EVIDENCE)")
check("config 임포트 가능 (dotenv 없이)", r.stdout.strip().endswith("True"), True)

# 대조군: 차단이 실제로 작동하는지 — langchain 을 쓰는 모듈은 반드시 실패해야 한다
r = run_isolated("import harness.tools")
check("대조군: harness.tools 는 차단됨", "blocked" in (r.stdout + r.stderr), True)
r = run_isolated("import harness.graph")
check("대조군: harness.graph 는 차단됨", "blocked" in (r.stdout + r.stderr), True)

print("\n[2] 차단 상태에서 게이트가 실제로 판정하는가")

# 검증 대상을 features.json 에서 동적으로 고른다 — 특정 ID 에 묶으면
# 그 기능이 구현되는 순간 테스트가 깨진다 (실제로 F-005 에서 발생했다).
_all = json.loads(io.open("web_target/features.json", encoding="utf-8").read())
PASSING = next((f["id"] for f in _all if f.get("passes")), None)
PENDING = next((f["id"] for f in _all if not f.get("passes")), None)
assert PASSING, "통과 기능이 없어 통과 경로를 검증할 수 없습니다"
assert PENDING, "미구현 기능이 없어 거부 경로를 검증할 수 없습니다"
print(f"  (통과 검증 대상: {PASSING} / 거부 검증 대상: {PENDING})")
r = run_isolated(
    "from harness.cli import main; "
    f"raise SystemExit(main(['verify','{PASSING}','--project','./web_target']))"
)
check(f"{PASSING} 통과 판정 (종료 0)", r.returncode, 0)
check("근거 테스트 출력", "근거 테스트" in r.stdout, True)

r = run_isolated(
    "from harness.cli import main; "
    f"raise SystemExit(main(['verify','{PENDING}','--project','./web_target']))"
)
check(f"{PENDING} 거부 판정 (종료 1)", r.returncode, 1)
check("사유 제시", "검증하는 테스트가 없습니다" in r.stdout, True)

r = run_isolated(
    "from harness.cli import main; "
    "raise SystemExit(main(['verify','NOPE','--project','./web_target']))"
)
check("없는 ID → 입력 오류 (종료 2)", r.returncode, 2)

print("\n[3] 플래그 불변성 — 거부 시 features.json 이 바뀌지 않는가")
before = Path("web_target/features.json").read_text(encoding="utf-8")
r = run_isolated(
    "from harness.cli import main; "
    f"raise SystemExit(main(['mark','{PENDING}','--project','./web_target']))"
)
after = Path("web_target/features.json").read_text(encoding="utf-8")
check("mark 거부 (종료 1)", r.returncode, 1)
check("features.json 무변경", after == before, True)

print("\n[4] 게이트 정책 단일 구현 — CLI 와 langchain 도구가 같은 판정")
from harness import verify
from harness.tools import update_features


def fake_results(tests):
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "numTotalTests": len(tests), "numPassedTests": passed, "numFailedTests": failed,
        "numTotalTestSuites": 1, "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{"name": "f.test.tsx", "assertionResults": [
            {"fullName": n, "title": n, "ancestorTitles": [], "status": s}
            for n, s in tests]}],
    }


def fresh_project(tmp_prefix):
    root = Path(tempfile.mkdtemp(prefix=tmp_prefix))
    (root / "features.json").write_text(json.dumps([
        {"id": "B-001", "description": "태그 있음", "passes": False, "steps": ["s1"]},
        {"id": "B-002", "description": "태그 없음", "passes": False, "steps": ["s1"]},
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    return root


original = verify.run_jest_json
verify.run_jest_json = lambda project_root: (
    fake_results([("B-001.1: 단계 1", "passed"), ("무관", "passed")]), ""
)
try:
    # 같은 상황에 두 경로를 통과시켜 결과가 일치하는지 본다
    root_cli = fresh_project("ts010-cli-")
    applied_cli, msg_cli = verify.apply_flag(str(root_cli), 0, passes=True)
    root_tool = fresh_project("ts010-tool-")
    msg_tool = update_features.invoke(
        {"project_root": str(root_tool), "feature_index": 0, "passes": True}
    )
    check("CLI 경로: 반영됨", applied_cli, True)
    check("도구 경로도 반영됨", msg_tool.startswith("[완료]"), True)
    check("메시지 동일", msg_cli, msg_tool)

    cli_feat = json.loads((root_cli / "features.json").read_text(encoding="utf-8"))[0]
    tool_feat = json.loads((root_tool / "features.json").read_text(encoding="utf-8"))[0]
    check("증거 블록 동일 (타임스탬프 제외)",
          {k: v for k, v in cli_feat["verification"].items() if k != "verified_at"},
          {k: v for k, v in tool_feat["verification"].items() if k != "verified_at"})

    # 태그 없는 기능은 두 경로 모두 거부
    root_cli2 = fresh_project("ts010-cli2-")
    applied2, msg2 = verify.apply_flag(str(root_cli2), 1, passes=True)
    root_tool2 = fresh_project("ts010-tool2-")
    msg_tool2 = update_features.invoke(
        {"project_root": str(root_tool2), "feature_index": 1, "passes": True}
    )
    check("CLI: 태그 없으면 거부", applied2, False)
    check("도구: 태그 없으면 거부", msg_tool2.startswith("[거부]"), True)
    check("거부 메시지 동일", msg2, msg_tool2)
finally:
    verify.run_jest_json = original

print("\n[5] 패키지 지연 로딩")
r = run_isolated(
    "import harness, sys; "
    "import harness.verify; "
    "print('langchain_core' in sys.modules, 'langgraph' in sys.modules)"
)
check("verify 임포트가 langchain 을 끌어오지 않음", r.stdout.strip().endswith("False False"), True)
check("재export 는 접근 시점에만 해석",
      "build_harness_graph" in dir(__import__("harness")), True)

print(f"\n{'='*60}")
print(f"TS-010 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

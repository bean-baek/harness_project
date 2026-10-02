"""
TS-018 검증 스크립트 — 유료 경로 스모크 테스트
──────────────────────────────────────────────
**LLM 을 스텁으로 바꿔 LangGraph 그래프를 실제로 끝까지 돌린다. 토큰 0.**

왜 필요한가:
  커버리지로 측정한 결과 유료 경로는 함수 본문이 **한 줄도** 실행되지 않았다.
    harness/graph.py        74줄 중 실제 로직 1줄 (모듈 상수)
    harness/router.py       94줄 중 1줄
    harness/nodes/agents.py 125줄 중 1줄
    harness/memory.py       66줄 중 1줄
  그 상태로 TS-017 에서 `verify.py`·`tags.py`·`mutate.py` 를 리팩터했다.
  `tools.py` 는 `verify.apply_flag` 를 호출하는데 **아무것도 그 연결을 검사하지 않았다.**
  살아 있었지만 그것은 검증이 아니라 운이었다 — TS-015 와 같은 구조다.

스텁 지점:
  모든 에이전트 노드가 `_get_llm()` → `bind_tools()` → `invoke_llm(.., node=...)` 를 거친다.
  `invoke_llm` 이 **노드 이름을 인자로 받는다**는 점을 이용해 노드별 응답을 주입한다.
  큐 순서에 의존하지 않으므로 라우팅이 바뀌어도 테스트가 거짓 통과하지 않는다.

무엇을 검증하는가:
  1) 그래프가 조립되고 **모든 노드·라우터가 실제로 호출되는가**
  2) ToolNode 가 **진짜 도구를 실행**하는가 (읽기 도구, 실제 파일)
  3) **리팩터된 증거 게이트에 유료 경로가 도달하는가** ← TS-017 의 맹점
  4) silent-abort 가드가 작동하는가 (TS-004)
  5) IRREVERSIBLE 도구가 interrupt 로 그래프를 멈추는가 (3계층 권한)
  6) LLM 장애가 전용 종료 코드로 변환되는가 (TS-005)
  7) 재시도 소진이 escalate 로 가는가
  8) Reflexion 반성이 디스크에 기록되는가 (TS-007 인접)

네트워크·API 키·실제 jest 를 쓰지 않는다. `ChatGoogleGenerativeAI` 는 생성조차 되지 않는다.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import config
import exit_codes

ok = 0
fail = 0
_tmpdirs: list[Path] = []


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {name}  -> {got!r}")
    else:
        fail += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


def tmp_project(*, with_spec=True, with_progress=True, features=None) -> Path:
    """격리된 대상 프로젝트. git 저장소가 아니므로 git_commit 은 안전하게 실패한다."""
    root = Path(tempfile.mkdtemp(prefix="ts018-"))
    _tmpdirs.append(root)
    if with_spec:
        (root / "features.json").write_text(
            json.dumps(features if features is not None else [
                {"id": "F-001", "description": "첫 기능", "passes": False, "steps": ["s1"]},
            ], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if with_progress:
        (root / "gemini-progress.txt").write_text("이전 세션 핸드오프\n", encoding="utf-8")
    return root


# ══════════════════════════════════════════════════════════════════════════════
# 스텁
# ══════════════════════════════════════════════════════════════════════════════

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from harness import memory as memory_mod                                   # noqa: E402
from harness.llm_errors import LLMUnavailableError                         # noqa: E402
from harness.nodes import agents                                          # noqa: E402


class _ExplodingLLM:
    """실제 LLM 클래스 자리에 끼우는 센티넬.

    `.env` 가 로드되므로 GOOGLE_API_KEY 의 부재로는 '호출 안 했음'을 증명할 수 없다.
    생성 자체를 막아 **네트워크 호출 0회**를 구조적으로 보장한다.
    """

    constructed = 0

    def __init__(self, *_a, **_kw):
        type(self).constructed += 1
        raise AssertionError(
            "실제 ChatGoogleGenerativeAI 가 생성됐다 — 스텁이 새고 있다 (토큰이 나갈 수 있다)"
        )


#: 모듈 전역에서 교체한다. 복원은 마지막 섹션에서 한다.
_real_chat_cls = agents.ChatGoogleGenerativeAI
agents.ChatGoogleGenerativeAI = _ExplodingLLM


class _StubLLM:
    """`bind_tools` 만 지원하는 껍데기. `invoke` 가 불리면 테스트 실패다 —
    실제 호출은 전부 스텁된 `invoke_llm` 이 가로채야 한다."""

    def __init__(self):
        self.bound_tools: list[str] = []

    def bind_tools(self, tools, **_kw):
        self.bound_tools = [getattr(t, "name", str(t)) for t in tools]
        return self

    def invoke(self, *_a, **_kw):                                   # pragma: no cover
        raise AssertionError("실제 LLM.invoke 가 호출됐다 — 스텁이 새고 있다")


class Script:
    """노드 이름 → 응답. 호출 순서를 기록한다.

    값이 리스트면 호출마다 하나씩 꺼내 쓴다(같은 노드의 n번째 호출).
    고갈되면 마지막 값을 반복한다 — 루프가 돌아도 테스트가 멈추지 않는다.
    """

    def __init__(self, table: dict):
        self.table = {k: (v if isinstance(v, list) else [v]) for k, v in table.items()}
        self.calls: list[str] = []
        self.bound: dict[str, list[str]] = {}

    def __call__(self, llm, messages, *, node="", **_kw):
        self.calls.append(node)
        if isinstance(llm, _StubLLM):
            self.bound[node] = llm.bound_tools
        queue = self.table.get(node)
        if queue is None:
            raise AssertionError(f"대본에 없는 노드가 호출됐다: {node!r}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def nodes(self) -> list[str]:
        """연속 중복을 접은 호출 순서."""
        out: list[str] = []
        for n in self.calls:
            if not out or out[-1] != n:
                out.append(n)
        return out


def ai(content="", tool_calls=None) -> AIMessage:
    """스크립트용 AI 응답. tool_calls 는 ToolNode 가 그대로 소비한다."""
    calls = []
    for i, (name, args) in enumerate(tool_calls or []):
        calls.append({"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"})
    return AIMessage(content=content, tool_calls=calls)


def run_graph(script: Script, root: Path, *, task="테스트 기능", max_retry=5,
              session="ts018"):
    """스텁을 끼우고 실 그래프를 돌린다.

    `stream(stream_mode="values")` 로 **중간 상태를 전부 보관**한다. 최종 상태만
    보면 안 되는 이유: `error_log` 는 Reflector 가 RESET_SENTINEL 로 의도적으로
    비우므로(state.keep_last_n 규약) silent-abort 마커가 최종 상태에 남지 않는다.
    마커가 '언젠가 설정됐다'를 검증하려면 중간 상태가 필요하다.

    Returns: (최종 상태, 중간 상태 목록, app, config, 메모리 디렉터리)
    """
    from harness.graph import build_harness_graph
    from harness.state import create_initial_state
    from langchain_core.messages import HumanMessage

    orig_get_llm, orig_invoke = agents._get_llm, agents.invoke_llm
    orig_mem = memory_mod.MEMORY_DIR
    mem_dir = Path(tempfile.mkdtemp(prefix="ts018-mem-"))
    _tmpdirs.append(mem_dir)
    agents._get_llm = lambda *a, **k: _StubLLM()
    agents.invoke_llm = script
    memory_mod.MEMORY_DIR = mem_dir
    try:
        app = build_harness_graph(max_retry=max_retry)
        state = create_initial_state(
            task=task, project_root=str(root), session_id=session, max_retry=max_retry,
        )
        state["messages"] = [HumanMessage(content=task)]
        cfg = {"configurable": {"thread_id": session}}
        chunks = list(app.stream(state, cfg, stream_mode="values"))
        final = chunks[-1] if chunks else state
        return final, chunks, app, cfg, mem_dir
    finally:
        agents._get_llm, agents.invoke_llm = orig_get_llm, orig_invoke
        memory_mod.MEMORY_DIR = orig_mem


# ══════════════════════════════════════════════════════════════════════════════
print("\n[1] 그래프 조립 — 노드와 엣지가 전부 등록되는가")
from harness.graph import build_harness_graph                              # noqa: E402

app0 = build_harness_graph()
nodes = set(app0.get_graph().nodes)
for expected in ("initializer", "orchestrator", "reason", "act", "evaluate",
                 "reflect", "human_check", "escalate", "done", "no_progress_guard"):
    check(f"노드 {expected} 등록", expected in nodes, True)
check("체크포인터 설정됨 (interrupt 가 동작하려면 필수)", app0.checkpointer is not None, True)


# ══════════════════════════════════════════════════════════════════════════════
print("\n[2] 전체 성공 사이클 — orchestrator → reason → act → reason → evaluate → done")
root = tmp_project()
script = Script({
    "orchestrator":  ai("기존 프로젝트 확인됨. 바로 구현한다."),
    "reason(coder)": [
        ai("명세를 읽는다", [("read_features", {"project_root": "PROJECT_ROOT"})]),
        ai("구현을 마쳤다"),
    ],
    "evaluate": ai("<score>90</score>\n<verdict>PASS</verdict>\n<critical></critical>"),
})
# read_features 인자에 실제 경로를 넣는다
script.table["reason(coder)"][0] = ai(
    "명세를 읽는다", [("read_features", {"project_root": str(root)})]
)
final, chunks, _, _, mem = run_graph(script, root)

check("노드 호출 순서", script.nodes(), ["orchestrator", "reason(coder)", "evaluate"])
check("최종 status", final.get("status"), "done")
check("평가 점수 파싱", final.get("evaluation_score"), 90)
check("평가 판정 파싱", final.get("evaluation_verdict"), "PASS")

tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
check("ToolNode 가 실제 도구를 실행했다", len(tool_msgs) >= 1, True)
check("도구가 진짜 파일을 읽었다 (F-001 이 내용에 있다)",
      any("F-001" in str(m.content) for m in tool_msgs), True)
check("coder 에게 CODER_TOOLS 가 바인딩됐다",
      "update_features" in script.bound.get("reason(coder)", []), True)
check("orchestrator 는 쓰기 도구를 받지 않는다 (READ_ONLY 계층)",
      "write_file" in script.bound.get("orchestrator", []), False)
# write_progress 는 **추가(append)** 한다 — 이전 핸드오프를 덮지 않는다
progress = (root / "gemini-progress.txt").read_text(encoding="utf-8")
check("done 노드가 세션 핸드오프를 기록했다", "세션" in progress and len(progress) > 20, True)
check("이전 핸드오프를 덮지 않았다 (append 규약)", progress.startswith("이전 세션"), True)
check("핸드오프에 평가 점수가 담겼다", "90" in progress, True)

import main                                                                # noqa: E402
check("종료 코드 = OK", main.exit_code_for_state(final), exit_codes.OK)


# ══════════════════════════════════════════════════════════════════════════════
print("\n[3] 리팩터된 증거 게이트에 유료 경로가 도달하는가 (TS-017 의 맹점)")
from harness import verify                                                 # noqa: E402

orig_json, orig_cov = verify.run_jest_json, verify.coverage_for_feature


def fake_suite(tests):
    passed = sum(1 for _, s in tests if s == "passed")
    failed = sum(1 for _, s in tests if s == "failed")
    return {
        "numTotalTests": len(tests), "numPassedTests": passed, "numFailedTests": failed,
        "numTotalTestSuites": 1, "numFailedTestSuites": 1 if failed else 0,
        "testResults": [{"assertionResults": [
            {"fullName": n, "title": n, "ancestorTitles": [], "status": s} for n, s in tests
        ]}],
    }


try:
    # 3-A 태그 테스트 없음 → 게이트가 거부해야 한다
    verify.run_jest_json = lambda pr: (fake_suite([("무관한 테스트", "passed")]), "")
    verify.coverage_for_feature = lambda *a, **k: (
        {"covered_statements": 10, "files_touched": 1, "sources": ["x.ts (10)"]}, "")
    root = tmp_project()
    script = Script({
        "orchestrator":  ai("바로 기록을 시도한다"),
        "reason(coder)": [
            ai("완료 표시", [("update_features",
                           {"project_root": str(root), "feature_index": 0, "passes": True})]),
            ai("기록 시도를 마쳤다"),
        ],
        "evaluate": ai("<score>80</score><verdict>PASS</verdict>"),
    })
    final, _, _, _, _ = run_graph(script, root, session="ts018-gate-a")
    tms = [str(m.content) for m in final["messages"] if isinstance(m, ToolMessage)]
    gate_msg = next((t for t in tms if "거부" in t or "완료" in t), "")
    check("게이트가 거부 메시지를 돌려줬다", "[거부]" in gate_msg, True)
    check("사유가 '검증하는 테스트가 없습니다'", "테스트가 없습니다" in gate_msg, True)
    saved = json.loads((root / "features.json").read_text(encoding="utf-8"))
    check("플래그가 변경되지 않았다", saved[0]["passes"], False)

    # 3-B 태그 테스트 있음 + 커버리지 → 게이트가 반영해야 한다
    verify.run_jest_json = lambda pr: (
        fake_suite([("F-001: 첫 기능을 검증한다", "passed")]), "")
    root = tmp_project()
    script = Script({
        "orchestrator":  ai("기록한다"),
        "reason(coder)": [
            ai("완료 표시", [("update_features",
                           {"project_root": str(root), "feature_index": 0, "passes": True})]),
            ai("끝"),
        ],
        "evaluate": ai("<score>85</score><verdict>PASS</verdict>"),
    })
    final, _, _, _, _ = run_graph(script, root, session="ts018-gate-b")
    tms = [str(m.content) for m in final["messages"] if isinstance(m, ToolMessage)]
    gate_msg = next((t for t in tms if "완료" in t or "거부" in t), "")
    check("게이트가 통과시켰다", "[완료]" in gate_msg, True)
    saved = json.loads((root / "features.json").read_text(encoding="utf-8"))
    check("플래그가 반영됐다", saved[0]["passes"], True)
    check("증거 블록이 기록됐다", "verification" in saved[0], True)
    check("증거에 기능 ID 를 인용한 테스트가 담겼다",
          any("F-001" in t for t in saved[0]["verification"]["evidence_tests"]), True)
    check("증거 출처(커버리지)가 담겼다",
          "evidence_sources" in saved[0]["verification"], True)
finally:
    verify.run_jest_json, verify.coverage_for_feature = orig_json, orig_cov


# ══════════════════════════════════════════════════════════════════════════════
print("\n[4] silent-abort 가드 (TS-004) — 도구를 하나도 부르지 않으면 Reflexion 으로")
root = tmp_project(with_spec=False, with_progress=False)   # → initializer 경로
script = Script({
    "initializer":   ai("초기화 완료"),
    "reason(coder)": [
        ai("음... 무엇을 해야 할지 모르겠다"),          # 도구 없음 → 가드
        ai("이제 읽어본다", [("read_features", {"project_root": str(root)})]),
        ai("끝났다"),
    ],
    "reflect":  ai("<reflection><root_cause>목표가 추상적이었다</root_cause></reflection>"),
    "evaluate": ai("<score>78</score><verdict>PASS</verdict>"),
})
final, chunks, _, _, mem = run_graph(script, root, session="ts018-abort")
check("initializer 경로로 진입 (명세·진행파일 없음)",
      script.nodes()[0], "initializer")
check("silent-abort 후 reflect 가 호출됐다", "reflect" in script.calls, True)
check("no_progress 상태를 거쳤다",
      any(c.get("status") == "no_progress" for c in chunks), True)
# 마커는 **중간 상태에서** 확인한다 — Reflector 가 RESET_SENTINEL 로 비우기 때문
check("error_log 에 silent-abort 마커가 설정됐다",
      any(any("[silent-abort]" in str(e) for e in (c.get("error_log") or []))
          for c in chunks), True)
check("Reflector 가 오류 로그를 초기화했다 (RESET_SENTINEL 규약)",
      final.get("error_log"), [])
check("반성이 상태에 누적됐다", len(final.get("reflections", [])) >= 1, True)
refl_files = list(mem.rglob("reflection_*.json"))
check("반성이 디스크에 기록됐다 (에피소드 메모리)", len(refl_files) >= 1, True)
if refl_files:
    saved_refl = json.loads(refl_files[0].read_text(encoding="utf-8"))
    check("반성 파일에 root_cause 가 담겼다",
          "root_cause" in str(saved_refl.get("reflection", "")), True)
check("가드를 거친 뒤에도 사이클이 완주했다", final.get("status"), "done")


# ══════════════════════════════════════════════════════════════════════════════
print("\n[5] IRREVERSIBLE 도구 → interrupt 로 그래프 정지 (3계층 권한)")
root = tmp_project()
script = Script({
    "orchestrator":  ai("배포하겠다"),
    "reason(coder)": ai("운영 배포", [("deploy_prod", {"target": "production"})]),
})
final, chunks, app, cfg, _ = run_graph(script, root, session="ts018-irrev")
# 정지 지점은 `compile(interrupt_before=["human_check"])` 이므로 노드 **진입 전**이다.
# main.py 의 `_handle_human_approval` 도 같은 방식으로 판별한다 — 같은 계약을 검증한다.
snapshot = app.get_state(cfg)
check("그래프가 human_check 앞에서 멈췄다", snapshot.next, ("human_check",))
check("compile 에 interrupt_before 가 설정돼 있다",
      "human_check" in (app.interrupt_before_nodes or []), True)
check("act 노드는 실행되지 않았다 (비가역 도구가 차단됨)",
      any(isinstance(m, ToolMessage) for m in final.get("messages", [])), False)
check("라우터가 human_check 로 보냈다 (evaluate/act 가 아니다)",
      "evaluate" in script.calls, False)
# 승인하면 reason 으로 복귀한다 — Command(resume=...) 계약
from langgraph.types import Command as _Cmd                                # noqa: E402
script.table["reason(coder)"] = [ai("승인받아 다시 생각한다")]
resumed = app.invoke(_Cmd(resume={"approved": False, "instruction": "하지 마십시오"}), cfg)
check("거부하면 status 가 cancelled", resumed.get("status"), "cancelled")
check("거부 사유가 metadata 에 기록됐다",
      (resumed.get("metadata") or {}).get("cancelled_by_human"), True)
check("종료 코드 = ESCALATED (사람이 멈춘 것은 기능 실패가 아니다)",
      __import__("main").exit_code_for_state(resumed), exit_codes.ESCALATED)

from harness.tools import is_irreversible                                  # noqa: E402
check("deploy_prod 는 IRREVERSIBLE", is_irreversible("deploy_prod"), True)
check("update_features 는 IRREVERSIBLE 아님", is_irreversible("update_features"), False)
check("모르는 도구는 보수적으로 STATEFUL", is_irreversible("unknown_tool"), False)


# ══════════════════════════════════════════════════════════════════════════════
print("\n[6] LLM 장애 → 전용 종료 코드 (TS-005)")
root = tmp_project()
script = Script({
    "orchestrator": LLMUnavailableError(
        "quota_exhausted",
        "429 You exceeded your current quota. Please check your plan and billing details.",
        node="orchestrator", attempts=1,
    ),
})
orig_get_llm, orig_invoke = agents._get_llm, agents.invoke_llm
agents._get_llm = lambda *a, **k: _StubLLM()
agents.invoke_llm = script
try:
    state = main.run_harness(
        task="테스트", project_root=str(root), session_id="ts018-quota", stream=False,
    )
finally:
    agents._get_llm, agents.invoke_llm = orig_get_llm, orig_invoke

check("쿼터 소진이 트레이스백으로 터지지 않았다", isinstance(state, dict), True)
check("metadata 에 llm_unavailable 마커", "llm_unavailable" in (state.get("metadata") or {}), True)
check("마커에 분류가 담겼다",
      (state.get("metadata") or {}).get("llm_unavailable", {}).get("kind"), "quota_exhausted")
check("종료 코드 = LLM_UNAVAILABLE(3)",
      main.exit_code_for_state(state), exit_codes.LLM_UNAVAILABLE)
check("3 은 인프라 실패로 분류된다 (기능 실패가 아니다)",
      exit_codes.LLM_UNAVAILABLE in exit_codes.FATAL_INFRA, True)


# ══════════════════════════════════════════════════════════════════════════════
print("\n[7] 도구 실패 감지 (TS-018 이 잡은 버그) — 한국어 오류도 Reflexion 을 촉발하는가")
from harness.router import TOOL_FAILURE_RE                                 # noqa: E402

# 실측 근거: harness/tools.py 의 도구들은 실패를 **예외가 아니라 한국어 문자열로 반환**한다.
# 영어만 보는 정규식은 그 전부를 놓쳤다 — 도구 실패에 Reflexion 이 한 번도 안 돌았다.
check("한국어 [오류] 를 실패로 인식", bool(TOOL_FAILURE_RE.search(
    "[오류] 파일을 찾을 수 없습니다: C:/nope.txt")), True)
check("[보안 오류] 를 실패로 인식", bool(TOOL_FAILURE_RE.search(
    "[보안 오류] 비밀키/환경변수 파일 읽기는 금지됩니다.")), True)
check("영어 Error 도 계속 인식 (기존 동작 보존)",
      bool(TOOL_FAILURE_RE.search("Error: something broke")), True)
check("Traceback 인식", bool(TOOL_FAILURE_RE.search("Traceback (most recent call last)")), True)
# 게이트 거부는 **판정**이지 장애가 아니다 — Reflexion 예산을 쓰지 않아야 한다
check("게이트의 [거부] 는 오류로 보지 않는다", bool(TOOL_FAILURE_RE.search(
    "[거부] 'F-001': passes=true 를 반영하지 않았습니다.")), False)
check("정상 출력은 오류가 아니다", bool(TOOL_FAILURE_RE.search(
    "[완료] features.json 업데이트")), False)

# 도구 반환값이 실제로 그 모양인지 확인한다 — 정규식만 맞아도 소용없다
from harness.tools import read_file                                        # noqa: E402

missing = read_file.invoke({"path": "C:/__ts018_does_not_exist__/x.txt"})
check("read_file 이 실패를 문자열로 반환한다 (예외를 올리지 않는다)",
      isinstance(missing, str), True)
check("그 문자열이 TOOL_FAILURE_RE 에 걸린다", bool(TOOL_FAILURE_RE.search(missing)), True)

print("\n[8] 재시도 소진 → escalate")
root = tmp_project()


def bad_read():
    """없는 파일 읽기 → 도구가 `[오류]` 문자열을 반환한다.

    **매번 새 AIMessage 를 만들어야 한다.** `add_messages` 리듀서는 메시지 `id` 로
    중복을 제거하므로 같은 인스턴스를 두 번 넣으면 두 번째는 *갱신*으로 처리되어
    messages 가 늘지 않는다. 그러면 `messages[-1]` 이 ToolMessage 로 남아
    `route_after_reason` 이 'act' 대신 'evaluate' 로 보낸다 — 실측으로 걸린 함정이다.
    """
    return ai("파일을 읽는다", [("read_file", {"path": "C:/__ts018_nope__/a.txt"})])


script = Script({
    "orchestrator":  ai("시작"),
    "reason(coder)": [bad_read() for _ in range(5)],
    "reflect":       ai("<reflection><root_cause>경로가 틀렸다</root_cause></reflection>"),
})
final, chunks, _, _, _ = run_graph(script, root, max_retry=1, session="ts018-esc")
check("도구 실패가 reflect 를 촉발했다", "reflect" in script.calls, True)
check("evaluate 로 새지 않았다 (실패를 성공으로 보지 않는다)", "evaluate" in script.calls, False)
check("재시도 소진 후 escalate", final.get("status"), "escalated")
check("종료 코드 = ESCALATED(1)", main.exit_code_for_state(final), exit_codes.ESCALATED)
check("에스컬레이션 보고서가 메시지에 담겼다",
      any("에스컬레이션" in str(getattr(m, "content", "")) or
          "재시도" in str(getattr(m, "content", "")) for m in final.get("messages", [])), True)

# TS-018 이 잡은 두 번째 버그: Reflector 가 도구 실패를 **보지 못한 채** 반성했다.
# 라우터는 실패를 감지해 reflect 로 보내지만 상태에 쓰지 않고, coder_node 의 오류
# 스캔은 LLM 응답 본문만(act 이전) 본다. 그래서 프롬프트에 "오류 로그 없음" 이 갔다.
print("\n[9] Reflector 가 실제 도구 실패를 받는가 (F-004 작화의 기계적 원인)")
prompts_seen: list[str] = []


class _Recorder(Script):
    def __call__(self, llm, messages, *, node="", **kw):
        if node == "reflect":
            prompts_seen.append(str(getattr(messages[-1], "content", "")))
        return super().__call__(llm, messages, node=node, **kw)


root = tmp_project()
script = _Recorder({
    "orchestrator":  ai("시작"),
    "reason(coder)": [bad_read() for _ in range(4)],
    "reflect":       ai("<reflection><root_cause>경로 오류</root_cause></reflection>"),
})
run_graph(script, root, max_retry=1, session="ts018-signal")
check("reflect 가 호출됐다", len(prompts_seen) >= 1, True)
joined = "\n".join(prompts_seen)
check("프롬프트에 '오류 로그 없음' 이 들어가지 않았다",
      "직접적인 오류 로그 없음" in joined, False)
check("프롬프트에 실제 도구 실패 내용이 담겼다", "[오류]" in joined, True)
check("실패한 도구 이름이 담겼다", "read_file" in joined, True)

from harness.nodes.agents import _tool_failures_from                       # noqa: E402

check("성공한 ToolMessage 는 신호로 넣지 않는다",
      _tool_failures_from([ToolMessage(content="[완료] 저장됨", tool_call_id="1",
                                       name="write_file")]), "")
check("status='error' 인 ToolMessage 는 내용과 무관하게 잡는다",
      "boom" in _tool_failures_from([ToolMessage(
          content="boom", tool_call_id="1", name="x", status="error")]), True)


# ══════════════════════════════════════════════════════════════════════════════
print("\n[10] 스텁 누출 방어 — 실제 LLM 이 단 한 번도 생성되지 않았는가")
# `.env` 가 로드되므로 GOOGLE_API_KEY 존재 여부로는 증명할 수 없다.
# 대신 모듈 전체에서 `ChatGoogleGenerativeAI` 를 **생성 즉시 터지는 센티넬**로
# 바꿔 두었다 (아래 참조). 여기까지 왔다는 것 자체가 0회 생성의 증거다.
check("ChatGoogleGenerativeAI 가 센티넬로 교체된 상태로 전부 돌았다",
      agents.ChatGoogleGenerativeAI is _ExplodingLLM, True)
check("센티넬 생성 횟수 = 0 (네트워크 호출 0)", _ExplodingLLM.constructed, 0)
check("_get_llm 이 원래대로 복원됐다",
      agents._get_llm.__qualname__ == "_get_llm", True)
check("invoke_llm 이 원래대로 복원됐다",
      getattr(agents.invoke_llm, "__name__", "") == "invoke_llm", True)
agents.ChatGoogleGenerativeAI = _real_chat_cls

for d in _tmpdirs:
    shutil.rmtree(d, ignore_errors=True)

print(f"\n{'='*60}")
print(f"TS-018 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

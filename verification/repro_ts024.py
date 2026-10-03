"""
TS-024 검증 스크립트 — 발표된 수치가 조용히 거짓이 되는 것을 막는다
──────────────────────────────────────────────────────────────────
README 가 같은 측정값을 **네 번 다르게** 발표했다. 이틀 사이다.

  a53966f  F-005 돌연변이 점수 50%   fed5ac1  40%
  6d66152                    33%   5189a3d  50%

매번 측정 코드를 고치고 매번 산문의 수치를 손으로 갱신했으며, 한 번은 갱신을 빠뜨려
33% 와 50% 가 같은 문서에 동시에 들어 있었다. **죽은 설정과 같은 구조**다
(TS-007/TS-019) — 문서가 값을 주장하고 코드가 그것을 모른다.

검증 항목:
  1) `render` 가 결정론적인가 — diff 검사의 전제
  2) `check` 가 어긋남을 **양방향으로** 판정하는가 (일치/불일치/파일 없음)
  3) 비싼 측정은 값 대신 **산출 명령**을 싣는가
  4) 생성 파일이 "손으로 고치지 말 것"을 자기 안에 들고 있는가
  5) **README 산문에 살아 있는 수치가 다시 들어오지 않았는가** ← 재발 방지의 핵심
  6) CLI 가 생성·검증을 노출하는가

jest 를 한 번 돌린다(판별력). LLM 호출 없음.
"""
import re
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import status as status_mod

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


SAMPLE = {
    "features_total": 75, "features_passing": 6,
    "suite_tests": 51, "suite_failed": 0,
    "levels": {"suite": 75, "feature": 6, "step": 2},
    "discrimination": 0.92,
    "independence": {"cross-checked": 5, "single-channel": 1},
    "inspect_ok": 8, "inspect_violated": 2, "inspect_needs_intent": 2,
    "deadcode": {},
    "repro_scripts": 15, "failure_modes": 24,
}

print("\n[1] render — 결정론 (diff 검사의 전제)")
a = status_mod.render(SAMPLE)
b = status_mod.render(dict(SAMPLE))
check("같은 입력이면 같은 문자열", a, b)
check("딕셔너리 키 순서가 바뀌어도 같다",
      status_mod.render({k: SAMPLE[k] for k in reversed(list(SAMPLE))}), a)
check("값이 바뀌면 문자열이 바뀐다",
      status_mod.render({**SAMPLE, "features_passing": 7}) == a, False)
check("기능 통과를 싣는다", "| 기능 통과 | 6 / 75 |" in a, True)
check("판별력을 싣는다", "92.0%" in a, True)
check("수준별 통과를 싣는다", "| 증거 수준 `step` 통과 | 2 / 75 |" in a, True)
check("독립성 등급을 싣는다", "| 교차검증 (채널 2개) | 5 |" in a, True)
check("자기 감사 0 을 명시적으로 싣는다", "| 죽은 설정 | 0 |" in a, True)

# 측정 실패를 '0' 으로 위장하지 않는다 (TS-016 의 규칙)
err = status_mod.render({**SAMPLE, "discrimination_error": "jest 를 찾을 수 없습니다",
                         "levels": {}, "discrimination": None})
check("측정 실패를 수치로 위장하지 않는다", "측정 실패" in err, True)

print("\n[2] check — 어긋남을 양방향으로 판정하는가")
work = Path(tempfile.mkdtemp(prefix="ts024-"))
(work / "docs").mkdir()
orig_collect = status_mod.collect
try:
    status_mod.collect = lambda pr, hr=".": dict(SAMPLE)

    matched, diag = status_mod.check("x", work)
    check("파일이 없으면 불일치", matched, False)
    check("생성 방법을 안내", "cli status" in diag, True)

    path, text = status_mod.write("x", work)
    check("생성 경로", path.name, "status.md")
    matched, diag = status_mod.check("x", work)
    check("생성 직후에는 일치", matched, True)
    check("일치 시 진단은 비어 있다", diag, "")

    # 사람이 수치를 거짓으로 고치면 잡는다
    p = work / status_mod.STATUS_PATH
    p.write_text(text.replace("| 기능 통과 | 6 / 75 |", "| 기능 통과 | 99 / 75 |"),
                 encoding="utf-8")
    matched, diag = status_mod.check("x", work)
    check("손으로 고친 값을 잡는다", matched, False)
    check("문서가 거짓이라고 말한다", "거짓을 말하고 있습니다" in diag, True)
    check("재생성 방법을 안내", "cli status" in diag, True)
    check("diff 를 보여준다", "---" in diag and "+++" in diag, True)

    # 측정값이 바뀌면 (코드가 바뀐 경우) 잡는다
    status_mod.write("x", work)
    status_mod.collect = lambda pr, hr=".": {**SAMPLE, "inspect_violated": 0}
    matched, _ = status_mod.check("x", work)
    check("측정값이 바뀌면 잡는다 (코드 변경 감지)", matched, False)
finally:
    status_mod.collect = orig_collect

print("\n[3] 비싼 측정은 값 대신 산출 명령을 싣는가")
check("돌연변이는 명령만", "`cli mutate <기능>`" in a, True)
check("돌연변이 점수 값은 싣지 않는다", bool(re.search(r"돌연변이[^|]*\|\s*[0-9]+%", a)), False)
check("회귀 건수는 명령만", "repro_tsNNN.py" in a, True)
check("왜 싣지 않는지 적는다", "검증되지 않은 수치" in a, True)
check("커버리지도 제외 사유를 적는다", "TS-012" in a, True)
check("스크립트 개수는 싣는다 (즉시 셀 수 있다)", "| 회귀 검증 스크립트 | 15개 |" in a, True)

print("\n[4] 생성 파일이 경고를 자기 안에 들고 있는가")
check("손으로 고치지 말라고 적는다", "손으로 고치지 말 것" in a, True)
check("CI 가 검사한다고 적는다", "--check" in a, True)
check("재생성 명령을 적는다", "python -m harness.cli status" in a, True)
check("왜 이 파일이 있는지 적는다 (TS-024)", "TS-024" in a, True)

print("\n[5] README 산문에 살아 있는 수치가 다시 들어오지 않았는가")
# 이것이 재발 방지의 핵심이다 — 수치를 걷어내도 다음에 또 넣으면 의미가 없다.
LIVE_PATTERNS = [
    # `\*\*?` 는 별표를 **최소 1개** 요구해 `점수 33%` (강조 없음)를 놓쳤다 —
    # README 에 그 형태로 낡은 값이 남아 있었다 (TS-026 에서 발견). `\*{0,2}` 로 고친다.
    (r"점수 \*{0,2}\d+%", "돌연변이 점수"),
    (r"판별력 \*\*\d+%", "판별력 수치"),
    (r"Discrimination \*\*\d+%", "판별력 수치(영문)"),
    (r"기능 \d+/75", "기능 통과 수"),
    (r"\d+/75 features", "기능 통과 수(영문)"),
    (r"jest \d+/\d+", "jest 테스트 수"),
    (r"회귀 \d{3}건", "회귀 총건수"),
    (r"\d{3} harness regression checks", "회귀 총건수(영문)"),
    (r"실패 모드 \*?\*?\d+건", "실패 모드 수"),
    (r"\*\*\d+ failure modes\*\*", "실패 모드 수(영문)"),
    (r"교차검증 \d+ ·", "독립성 분포"),
    (r"회귀 \d+건 \+", "모드 표의 회귀 건수"),
    (r"\d+ regression checks \+", "모드 표의 회귀 건수(영문)"),
    (r"all \d+ regression checks", "역사 서술 속 회귀 건수(영문)"),
]
# 두 README 만 보던 것을 **산문이 있는 모든 파일**로 넓혔다 (TS-026 에서 발견).
# `ci.yml` 의 주석에 "회귀 699건" 을 적었고 이 검사가 보지 않아 통과했다 — 같은
# 결함이 같은 날 다른 파일에서 재발했다. 산문은 README 에만 있는 것이 아니다.
SCANNED_DOCS = (
    "README.md",
    "README_EN.md",
    "verification/README.md",
    ".github/workflows/ci.yml",
    "troubleshooting/INDEX.md",
)
for doc in SCANNED_DOCS:
    text = (PROJECT / doc).read_text(encoding="utf-8")
    found = []
    for pat, label in LIVE_PATTERNS:
        for m in re.finditer(pat, text):
            line_no = text[:m.start()].count(NL) + 1
            found.append(f"{doc}:{line_no} [{label}] {m.group(0)}")
    for f in found[:6]:
        print(f"        {f}")
    check(f"{doc} 에 살아 있는 수치 0건", len(found), 0)

# 역사적 서술은 **허용**된다 — 고친 결함의 '전' 수치는 드리프트하지 않는다
ko = (PROJECT / "README.md").read_text(encoding="utf-8")
check("역사적 수치는 유지된다 (190곳 중 3곳 — TS-021 의 '전')",
      "190곳" in ko, True)
check("역사적 수치는 유지된다 (콜드/웜 비용)", "10.8초" in ko, True)
check("생성 파일을 가리킨다", "docs/status.md" in ko, True)

print("\n[6] 실제 레포가 현재 일치하는가")
matched, diag = status_mod.check("web_target", PROJECT)
if not matched:
    print(f"        {diag[:200]}")
check("docs/status.md 가 현재 측정값과 일치", matched, True)

print("\n[7] CLI")
from harness.cli import build_parser

args = build_parser().parse_args(["status"])
check("status 서브명령", args.func.__name__, "cmd_status")
check("기본은 생성", args.check, False)
args2 = build_parser().parse_args(["status", "--check"])
check("--check 를 받는다", args2.check, True)

print(f"\n{'='*60}")
print(f"TS-024 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'='*60}")
sys.exit(1 if fail else 0)

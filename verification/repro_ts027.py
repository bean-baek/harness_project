"""
TS-027 검증 스크립트 — 노출 진단 (터지기 전에 묻는다)
──────────────────────────────────────────────────
기록된 실패 모드 26건은 전부 **터진 뒤에** 쓰였다. 기록은 재발을 막지만, 하네스를
다른 프로젝트에 붙이는 사람에게는 늦다 — 그 사람은 26건을 읽고 "내 프로젝트에
해당되는 것이 무엇인가"를 손으로 판단해야 했고, TS-025 가 보여준 것처럼 그 판단은
틀린다.

`cli exposure` 가 그 판단을 기계화한다. 핵심 설계는 **문서가 선언하고 코드가 검사**하며
**양방향으로 강제**한다는 것이다 (락파일 검사와 같은 모양 — TS-024 의 방식):

  TS 문서의 `exposure:` 키에 검사기가 없다        → 보고 + 종료 코드 1
  검사기가 있는데 아무 문서도 선언하지 않았다      → 보고 + 종료 코드 1 (고아 검사기)

노출 건수로는 차단하지 않는다. 노출은 결함이 아니라 **조건**이고, 차단하면
"노출 0건을 만들기 위해 진단을 끄는" 압력이 생긴다.

이 명령을 만들면서 실제로 결함 3건이 나왔다 (음성 대조로 전부 고정한다):

  1) `config.py` 의 `load_dotenv(override=True)` 가 **`.env` 로 실제 환경 변수를
     이겼다.** CI 와 문서는 `GOOGLE_API_KEY=""` 로 토큰 없는 경로를 '강제한다'고
     선언하는데 `.env` 가 있는 로컬에서는 그 선언이 아무 일도 하지 않았다 —
     선언된 가드가 죽어 있는 TS-007·019 와 같은 모양이다.
  2) `status.check(project, harness)` 에 인자를 거꾸로 넘겨 검사기가 예외를 던졌다.
     진단이 그것을 '확인불가 + 예외 내용'으로 보고해서 발견됐다.
  3) TS-024 검사기가 **외부 프로젝트를 거짓 양성으로** 보고했다. `docs/status.md` 는
     하네스가 자기 대상에 대해 생성하는 파일이라 픽스처와는 당연히 어긋난다.

LLM·네트워크를 쓰지 않는다.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 재현 스크립트는 verification/ 에 있으므로 루트는 한 단계 위다.
# 주의: 일부 검증이 "web_target" 을 **상대 경로**로 쓰므로 반드시
# 레포 루트에서 실행해야 한다 (`python verification/repro_tsXXX.py`).
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from harness import exposure
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


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


print("\n[1] 문서가 단일 출처인가 — frontmatter 를 읽는다")
modes = exposure.load_modes()
check("TS 문서를 읽었다", len(modes) >= 26, True)
check("id 를 읽는다", all(m.ts_id.startswith("TS-") for m in modes), True)
check("title 을 읽는다", all(m.title for m in modes), True)
# 선언 누락이 '해당 없음'으로 위장되지 않게, **모든** 문서가 선언해야 한다
no_key = [m.ts_id for m in modes if not m.exposure_key]
check("`exposure:` 를 선언하지 않은 문서가 없다", no_key, [])
no_guard = [m.ts_id for m in modes if not m.guard]
check("`guard:` 를 선언하지 않은 문서가 없다", no_guard, [])

print("\n[2] 양방향 강제 — 선언과 검사기가 일치하는가")
declared = {m.exposure_key for m in modes if m.exposure_key}
missing = sorted(declared - set(exposure.CHECKS))
orphans = sorted(set(exposure.CHECKS) - declared)
check("선언된 키에 검사기가 전부 있다", missing, [])
check("고아 검사기가 없다", orphans, [])
check("검사기가 전부 호출 가능하다", all(callable(f) for f in exposure.CHECKS.values()), True)

print("\n[3] 실제 레포 — 진단이 끝까지 도는가")
verdicts, miss, orph = exposure.diagnose("web_target", PROJECT)
check("판정 수 = 문서 수", len(verdicts), len(modes))
check("어긋남 없음 (선언)", miss, [])
check("어긋남 없음 (고아)", orph, [])
valid = {"protected", "exposed", "n/a", "unknown"}
check("모든 판정이 네 상태 중 하나다", {v.status for v in verdicts} <= valid, True)
check("모든 판정에 사유가 있다", all(v.detail for v in verdicts), True)

print("\n[4] 프로젝트 모양마다 다른 결과를 내는가 (이것이 목적이다)")
# 같은 결과만 낸다면 '진단'이 아니다. 모양이 다르면 노출이 달라야 한다.
profiles = {}
for label, path in (("web_target", "web_target"),
                    ("vanilla-js", "verification/fixtures/vanilla-js"),
                    ("pytest-app", "verification/fixtures/pytest-app")):
    project_mod.clear_cache()
    vs, _, _ = exposure.diagnose(path, PROJECT)
    profiles[label] = {v.mode.ts_id: v.status for v in vs}
project_mod.clear_cache()
check("세 모양의 진단이 서로 다르다",
      len({tuple(sorted(p.items())) for p in profiles.values()}), 3)
# 픽스처는 typecheck 가 없다 → 변이 유효성 확인이 불가능하다 (점수 과대평가)
check("vanilla-js: TS-021 노출 (typecheck 커맨드 없음)",
      profiles["vanilla-js"]["TS-021"], "exposed")
check("pytest-app: TS-021 노출 (typecheck 커맨드 없음)",
      profiles["pytest-app"]["TS-021"], "exposed")
check("web_target: TS-021 보호됨 (tsc 가 선언돼 있다)",
      profiles["web_target"]["TS-021"], "protected")
# 런너 실행 계층이 CI 에 있는 것은 jest 뿐이다 (TS-025 가 기록한 공백)
check("vanilla-js: TS-025 노출 (vitest 실행 계층 미검증)",
      profiles["vanilla-js"]["TS-025"], "exposed")
check("pytest-app: TS-025 노출 (pytest 실행 계층 미검증)",
      profiles["pytest-app"]["TS-025"], "exposed")
check("web_target: TS-025 보호됨 (jest 는 CI 가 실행한다)",
      profiles["web_target"]["TS-025"], "protected")

print("\n[5] '확인 불가' 와 '해당 없음' 을 섞지 않는가")
# 묻지 못한 것을 '발생하지 않는다'로 적으면 측정 실패가 안전으로 위장된다 (TS-016).
# TS-024 검사기가 그 거짓 양성을 냈다 — 외부 프로젝트를 '노출'로 보고했다.
project_mod.clear_cache()
ctx_fix = exposure.build_context("verification/fixtures/vanilla-js", PROJECT)
status_, detail = exposure.check_published_numbers(ctx_fix)
check("외부 프로젝트의 TS-024 는 확인불가다 (노출도 해당없음도 아니다)", status_, "unknown")
check("그 사유가 비교 대상이 없음을 말한다", "비교할 대상이 없다" in detail, True)
ctx_own = exposure.build_context("web_target", PROJECT)
status_own, _ = exposure.check_published_numbers(ctx_own)
check("하네스 자기 대상에서는 실제로 드리프트를 묻는다",
      status_own in ("protected", "exposed"), True)
project_mod.clear_cache()

print("\n[6] 검사기가 예외를 던져도 진단이 멈추지 않는가")
# 실제로 일어났다 — status.check 에 인자를 거꾸로 넘겨 FileNotFoundError 가 났다.
# 진단이 그것을 '확인불가 + 예외 내용'으로 보고해서 발견됐다. 삼켜서 'n/a' 로
# 적었다면 영원히 몰랐을 것이다.
orig = exposure.CHECKS.get("dead-config")
try:
    def boom(ctx):
        raise RuntimeError("일부러 터뜨린다")

    exposure.CHECKS["dead-config"] = boom
    vs, _, _ = exposure.diagnose("web_target", PROJECT)
    bad = [v for v in vs if v.mode.exposure_key == "dead-config"]
    check("예외를 던진 검사기는 확인불가로 보고된다",
          {v.status for v in bad}, {"unknown"})
    check("예외 내용을 사유에 담는다",
          all("일부러 터뜨린다" in v.detail for v in bad), True)
    check("나머지 판정은 정상적으로 나온다", len(vs), len(modes))
finally:
    if orig is not None:
        exposure.CHECKS["dead-config"] = orig

print("\n[7] 선언과 검사기가 어긋나면 종료 코드 1 인가")
# 노출 건수로는 차단하지 않는다 — 노출은 조건이다. 그러나 **선언과 검사기의
# 어긋남**은 사실 오류이고, 어긋난 채로는 '노출 n건'이 믿을 수 없는 값이 된다.
tmp = Path(tempfile.mkdtemp(prefix="harness-ts027-"))
write(tmp / "TS-900-fake.md", NL.join([
    "---", "id: TS-900", "title: 존재하지 않는 검사기를 선언한다",
    "severity: low", "guard: 없음", "exposure: 이런-검사기는-없다",
    # `resolution` 은 유효한 값을 넣는다 — 여기서 보려는 어긋남은 **검사기 부재**
    # 하나이고, 두 어긋남이 섞이면 어느 쪽이 보고됐는지 구별할 수 없다.
    "resolution: accept", "---", "", "본문",
]))
# 여기서 보려는 것도 선언의 어긋남이다. 판정 목록이 필요한 두 검사만
# 아래에서 따로 쓴다 — 그 둘을 위해 전체 진단을 한 번만 돌린다.
miss2, orph2 = exposure.validate_declarations(exposure.load_modes(tmp))
vs, _m, _o = exposure.diagnose("web_target", PROJECT, tmp)
check("검사기 없는 선언을 보고한다", len(miss2), 1)
check("그 판정은 확인불가다", vs[0].status, "unknown")
check("검사기 이름을 사유에 담는다", "이런-검사기는-없다" in vs[0].detail, True)
# 이 임시 디렉터리는 **존재하지 않는 키 하나만** 선언했으므로 실제 검사기는
# 전부 고아가 된다 — 23개 중 23개. (처음에 `len-1` 로 적었고 검증이 잡았다.)
check("고아 검사기도 전부 보고한다 (이 디렉터리는 실제 검사기를 하나도 선언하지 않았다)",
      len(orph2), len(exposure.CHECKS))
rendered = exposure.render(vs, miss2, orph2, "web_target")
check("보고가 어긋남을 **먼저** 알린다", "선언과 검사기가 어긋난다" in rendered, True)

# `resolution` 누락·오타도 같은 자리에서 막는다 (TS-030). 루프를 끊는 판정이
# 그 선언에 의존하므로, 선언이 없으면 "build 0건"이 믿을 수 없는 값이 된다.
tmp2 = Path(tempfile.mkdtemp(prefix="harness-ts027-res-"))
write(tmp2 / "TS-901-nores.md", NL.join([
    "---", "id: TS-901", "title: resolution 을 선언하지 않는다",
    "severity: low", "guard: 없음", "exposure: dead-config", "---", "", "본문",
]))
#
# `diagnose()` 가 아니라 `validate_declarations()` 를 부른다 — 선언 검증은
# frontmatter 를 읽는 일이고, `diagnose()` 를 부르면 jest·검수·독립성까지 돌아
# 호출당 20초가 든다. 실측에서 이 스크립트가 3분 42초였다 (TS-030).
miss3, _o3 = exposure.validate_declarations(exposure.load_modes(tmp2))
check("resolution 미선언을 보고한다",
      any("resolution" in m for m in miss3), True)
write(tmp2 / "TS-901-nores.md", NL.join([
    "---", "id: TS-901", "title: resolution 에 오타가 있다",
    "severity: low", "guard: 없음", "exposure: dead-config",
    "resolution: bulid", "---", "", "본문",       # 'build' 오타
]))
miss4, _o4 = exposure.validate_declarations(exposure.load_modes(tmp2))
check("resolution 오타도 보고한다 (세 값 중 하나여야 한다)",
      any("build/use/accept" in m for m in miss4), True)
write(tmp2 / "TS-901-nores.md", NL.join([
    "---", "id: TS-901", "title: 올바른 선언",
    "severity: low", "guard: 없음", "exposure: dead-config",
    "resolution: use", "---", "", "본문",
]))
miss5, _o5 = exposure.validate_declarations(exposure.load_modes(tmp2))
check("올바르면 resolution 어긋남이 없다",
      any("resolution" in m for m in miss5), False)
check("수치가 불완전하다고 적는다", "위 수치는 불완전하다" in rendered, True)

print("\n[8] CLI — 종료 코드")
env = dict(os.environ, PYTHONIOENCODING="utf-8", GOOGLE_API_KEY="")
r = subprocess.run([sys.executable, "-m", "harness.cli", "exposure"],
                   cwd=str(PROJECT), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env)
check("정상 진단은 종료 코드 0 (노출이 있어도 차단하지 않는다)", r.returncode, 0)
check("노출 항목을 출력한다", "노출 —" in r.stdout, True)
check("'확인 불가' 주의를 출력한다", "'확인 불가' 를 '해당 없음' 으로 읽지 말 것" in r.stdout, True)
r2 = subprocess.run([sys.executable, "-m", "harness.cli", "exposure",
                     "--troubleshooting", str(tmp)],
                    cwd=str(PROJECT), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=env)
check("어긋나면 종료 코드 1", r2.returncode, 1)
r3 = subprocess.run([sys.executable, "-m", "harness.cli", "exposure", "--all"],
                    cwd=str(PROJECT), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=env)
check("--all 이 보호됨 항목까지 출력한다", "[보호됨]" in r3.stdout, True)
check("기본 출력은 보호됨을 접는다", "[보호됨]" in r.stdout, False)

print("\n[9] .env 가 실제 환경 변수를 이기지 않는가 (TS-027 에서 발견)")
# `load_dotenv(override=True)` 였을 때 `.env` 가 환경 변수를 이겼다. CI 와 문서는
# `GOOGLE_API_KEY=""` 로 토큰 없는 경로를 강제한다고 선언하는데, 그 선언이
# `.env` 가 있는 로컬에서 아무 일도 하지 않았다 — **죽은 가드**다.
work = Path(tempfile.mkdtemp(prefix="harness-ts027-env-"))
write(work / ".env", "GOOGLE_API_KEY=from-dotenv" + NL)
probe = "import config; print(repr(config.GOOGLE_API_KEY))"
# 명시적으로 비운 환경 변수가 이겨야 한다
r4 = subprocess.run([sys.executable, "-c", probe], cwd=str(work),
                    capture_output=True, text=True, encoding="utf-8",
                    env=dict(os.environ, PYTHONPATH=str(PROJECT), GOOGLE_API_KEY=""))
check("명시적 빈 값이 .env 를 이긴다", r4.stdout.strip(), "''")
# 설정하지 않았으면 .env 가 빈 칸을 채운다 (기존 동작 보존)
env_no_key = {k: v for k, v in os.environ.items() if k != "GOOGLE_API_KEY"}
env_no_key["PYTHONPATH"] = str(PROJECT)
r5 = subprocess.run([sys.executable, "-c", probe], cwd=str(work),
                    capture_output=True, text=True, encoding="utf-8", env=env_no_key)
check("설정하지 않으면 .env 가 채운다 (하위호환)", r5.stdout.strip(), "'from-dotenv'")
# 음성 대조: override=True 였다면 첫 검사가 실패한다는 것을 같은 입력으로 보인다
check("음성 대조: .env 값과 빈 값은 구별 가능한 입력이다",
      r4.stdout.strip() != r5.stdout.strip(), True)

print("\n[10] 진단이 임계값이나 점수를 쓰지 않는가")
# 이 프로젝트가 `EVAL_WEIGHTS` 로 겪은 실수다 — 근거 없는 상수로 판정하면
# 그 수치를 방어할 방법이 없다. 노출 진단은 **사실 하나당 항목 하나**다.
src = (PROJECT / "harness" / "exposure.py").read_text(encoding="utf-8")
check("점수를 계산하지 않는다", "score" in src.lower(), False)
check("임계값 상수가 없다", "THRESHOLD" in src, False)
vs, _, _ = exposure.diagnose("web_target", PROJECT)
check("판정은 문자열 상태다 (수치가 아니다)",
      all(isinstance(v.status, str) for v in vs), True)

print(f"{NL}{'=' * 60}")
print(f"TS-027 검증 결과: PASS {ok} / FAIL {fail}")
print(f"{'=' * 60}")
sys.exit(1 if fail else 0)

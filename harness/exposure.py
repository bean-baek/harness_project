"""
harness/exposure.py
───────────────────
**이 프로젝트가 어떤 실패 모드에 노출되어 있는가 — 터지기 전에 묻는다.**

배경:
  `troubleshooting/` 에 기록된 실패 모드는 전부 **터진 뒤에** 쓰였다. 기록은
  재발을 막지만, **다른 프로젝트에 하네스를 붙이는 사람**에게는 늦다. 그 사람은
  26건을 읽고 "내 프로젝트에 해당되는 것이 무엇인가"를 **손으로** 판단해야 했다.

  TS-025 가 보여준 것처럼 그 판단은 틀린다. 하네스는 "모든 프로젝트에 붙는다"고
  선언했지만 두 번째 프로젝트에서 결함 5개가 나왔고, 그중 넷은 `web_target` 의
  모양에서는 **증상이 없는** 것이었다. 읽는 사람이 그걸 알 방법이 없었다.

설계 — 왜 문서가 선언하고 코드가 검사하는가:
  노출 조건을 파이썬 딕셔너리에 적으면 문서와 코드가 **두 개의 진실**이 된다.
  그것이 TS-007·TS-019 가 두 번 반복한 '죽은 설정'이다. 그래서 선언은
  **TS 문서의 frontmatter 에만** 둔다.

      guard:    재발을 막는 장치 (사람이 읽는 문장)
      exposure: 노출 여부를 기계로 묻는 **검사기 키**

  `cli exposure` 가 문서를 읽어 키를 해소한다. 그리고 **양방향으로 강제**한다:

      선언된 키에 검사기가 없다 → 보고한다 (조용히 건너뛰지 않는다)
      검사기가 있는데 아무 문서도 선언하지 않았다 → 보고한다 (고아 검사기)

  락파일 검사와 같은 모양이므로 오탐이 구조적으로 불가능하다 (TS-024 의 방식).

판정은 네 가지다 — 점수가 아니다:

  `protected`     노출 조건이 있고 **가드가 작동한다**
  `exposed`       노출 조건이 있고 **가드가 없거나 꺼져 있다**
  `n/a`           그 실패가 가능한 모양이 아니다 (예: 유료 경로를 쓰지 않는다)
  `unknown`       기계로 물을 수 없다 — 사람이 봐야 한다

`unknown` 을 `n/a` 로 합치지 않는 이유 (TS-016 의 규칙): "묻지 못했다"를
"해당 없다"로 적으면 **측정 실패가 안전으로 위장된다.** 둘은 다른 사실이다.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import config
from harness.project import ProjectConfig, config_for

#: frontmatter 한 줄 — `key: value`
_FM_LINE = re.compile(r"^([a-z_]+):\s*(.*)$")


@dataclass
class FailureMode:
    """TS 문서 한 건이 선언한 것."""

    ts_id: str
    title: str
    severity: str
    guard: str
    exposure_key: str
    doc: str
    #: 이 실패 모드가 **무엇으로** 해결되는가 (TS-030) — 루프를 끊는 사실 판정이다.
    #:
    #:   `build`   도구를 더 만들어야 한다
    #:   `use`     도구는 됐고 **실제로 써봐야** 한다 (예: pytest 프로젝트에 붙여보기)
    #:   `accept`  받아들이는 조건이다 (고칠 것이 없다)
    #:
    #: `exposed` + `build` 의 개수가 0 이면 **도구를 더 만들 이유가 없다.**
    #: 임계값이 아니라 개수이고, 선언은 TS 문서의 frontmatter 에만 있다.
    resolution: str = ""

    def short(self, width: int = 62) -> str:
        return self.title if len(self.title) <= width else self.title[:width - 1] + "…"


@dataclass
class Verdict:
    """노출 판정 한 건."""

    mode: FailureMode
    status: str          # 'protected' | 'exposed' | 'n/a' | 'unknown'
    detail: str

    def mark(self) -> str:
        return {"protected": "보호됨", "exposed": "노출  ",
                "n/a": "해당없음", "unknown": "확인불가"}.get(self.status, self.status)


@dataclass
class Context:
    """검사기가 보는 것. 한 번만 모아 모든 검사기가 공유한다.

    비싼 측정은 **접근자로 감싸 한 번만 계산한다** (TS-030). 검사기마다 따로 부르면
    같은 일을 여러 번 한다 — 실측에서 `deadcode.audit` 이 두 번(각 4초),
    `inspect_project` 가 한 번(10초) 불렸고 `cli exposure` 가 33초였다.
    """

    root: Path                      # 검사 대상 프로젝트
    harness_root: Path
    cfg: ProjectConfig
    features: list[dict] = field(default_factory=list)
    tag_ids: set[str] = field(default_factory=set)
    #: 지연 캐시 — 직접 읽지 말고 아래 접근자를 쓸 것
    _audit: list[Any] | None = field(default=None, repr=False)
    _report: Any = field(default=None, repr=False)

    def audit(self) -> list[Any]:
        """하네스 자기 감사 결과 (죽은 설정·고아 코드·미사용 임포트). 한 번만 돈다."""
        if self._audit is None:
            from harness import deadcode

            self._audit = deadcode.audit(self.harness_root)
        return self._audit

    def report(self) -> Any:
        """프로젝트 검수 결과. 한 번만 돈다."""
        if self._report is None:
            from harness import inspect as inspect_mod

            self._report = inspect_mod.inspect_project(self.harness_root)
        return self._report


# ── 문서 읽기 ────────────────────────────────────────────────────────────────

def load_modes(troubleshooting_dir: str | Path | None = None) -> list[FailureMode]:
    """TS 문서의 frontmatter 를 읽는다. **문서가 단일 출처다.**

    `guard` / `exposure` 가 없는 문서는 빈 값으로 담아 호출자가 그 사실을
    보고하게 한다 — 조용히 건너뛰면 선언 누락이 '해당 없음'으로 위장된다.
    """
    base = Path(troubleshooting_dir or config.TROUBLESHOOTING_DIR)
    out: list[FailureMode] = []
    for p in sorted(base.glob("TS-*.md")):
        text = p.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end < 0:
            continue
        fields: dict[str, str] = {}
        for line in text[3:end].strip().split("\n"):
            m = _FM_LINE.match(line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        out.append(FailureMode(
            ts_id=fields.get("id", p.stem),
            title=fields.get("title", ""),
            severity=fields.get("severity", ""),
            guard=fields.get("guard", ""),
            exposure_key=fields.get("exposure", ""),
            resolution=fields.get("resolution", ""),
            doc=p.name,
        ))
    return out


# ── 검사기 ───────────────────────────────────────────────────────────────────
#
# 각 검사기는 `(상태, 사유)` 를 돌려준다. 상태는 위 네 가지 중 하나다.
# 검사기는 **사실만** 묻는다 — 임계값이나 점수를 쓰지 않는다.

def _paid_path_in_use(ctx: Context) -> tuple[str, str]:
    """유료 경로(LangGraph + Gemini)를 쓰는가."""
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "exposed", ("API 키가 설정되어 유료 경로를 쓸 수 있다 — 스모크 테스트가 "
                           "배선을 고정하지만 실제 모델 거동은 보장하지 않는다")
    return "n/a", "API 키가 없다 — 토큰 없는 모드에서는 이 경로를 지나지 않는다"


def check_spec_path(ctx: Context) -> tuple[str, str]:
    """TS-001 — 명세 파일을 cwd 가 아니라 프로젝트 기준으로 찾는가."""
    from harness.verify import features_path

    p = features_path(str(ctx.root))
    if not p.is_file():
        return "exposed", f"명세 파일이 없다: {p}"
    try:
        p.resolve().relative_to(ctx.root.resolve())
    except ValueError:
        return "exposed", f"명세 파일이 프로젝트 밖에 있다: {p}"
    return "protected", f"명세를 프로젝트 안에서 찾는다: {p.name}"


def check_console_encoding(ctx: Context) -> tuple[str, str]:
    """TS-002/003 — 콘솔 인코딩이 UTF-8 이 아닌 환경인가 (Windows cp949)."""
    if platform.system() != "Windows":
        return "n/a", f"{platform.system()} — cp949 콘솔 문제가 발생하지 않는다"
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in enc:
        return "protected", f"콘솔이 {enc} — 출력이 깨지지 않는다"
    return "exposed", (
        f"콘솔이 {enc or '불명'} 이다. 서브프로세스 출력은 하네스가 "
        "errors='replace' 로 받아 안전하지만, **하네스 자신의 출력**은 "
        "UnicodeEncodeError 로 멈출 수 있다 — PYTHONIOENCODING=utf-8 을 권한다"
    )


def check_paid_path_exit(ctx: Context) -> tuple[str, str]:
    """TS-004 — 도구 호출 없는 응답이 성공으로 위장되는가."""
    return _paid_path_in_use(ctx)


def check_paid_path_quota(ctx: Context) -> tuple[str, str]:
    """TS-005 — 쿼터 초과가 기능 결함으로 오귀속되는가."""
    return _paid_path_in_use(ctx)


def check_test_evidence_gate(ctx: Context) -> tuple[str, str]:
    """TS-006 — 증거 없는 자가 채점이 가능한가.

    **두 조건을 함께 묻는다.** TS-006 은 결함이 둘이었다 — 게이트가 권고였고,
    그리고 `run_tests` 가 Windows 에서 **한 번도 동작하지 않았다.** 앞쪽만 확인하면
    "게이트가 켜져 있다"는 참인데도 게이트가 아무 증거도 못 얻는 상태를 놓친다.
    문서 하나가 키 하나를 선언하는 설계이므로 두 조건을 한 검사기에 둔다.
    """
    from harness.verify import runner_for

    if not config.REQUIRE_TEST_EVIDENCE:
        return "exposed", ("HARNESS_REQUIRE_TEST_EVIDENCE=false — 게이트가 꺼져 있다. "
                           "통과 플래그가 증거 없이 기록된다")
    try:
        runner = runner_for(str(ctx.root))
    except ValueError as exc:
        return "exposed", f"게이트는 켜져 있으나 런너를 결정할 수 없다: {exc}"
    available, note = runner.available()
    if not available:
        return "exposed", (
            f"게이트는 켜져 있으나 **{runner.name} 을 실행할 수 없다** — 증거를 얻을 "
            f"방법이 없어 모든 기능이 거부된다. {note}"
        )
    return "protected", (f"증거 게이트가 켜져 있고 {runner.name} 이 실행 가능하다 "
                         "(통과 플래그는 실제로 실행된 테스트를 요구한다)")


def check_dead_config(ctx: Context) -> tuple[str, str]:
    """TS-007/019 — 선언됐는데 아무도 읽지 않는 설정이 있는가."""
    dead = [f for f in ctx.audit() if f.kind == "dead-config"]
    if dead:
        return "exposed", f"죽은 설정 {len(dead)}건 — `cli deadcode` 로 확인"
    return "protected", "죽은 설정 0건 (`cli deadcode` 가 매 CI 마다 차단한다)"


def check_evidence_level(ctx: Context) -> tuple[str, str]:
    """TS-008 — '스위트 녹색'을 기능 증거로 오인하는가."""
    if config.EVIDENCE_LEVEL == "suite":
        return "exposed", ("HARNESS_EVIDENCE_LEVEL=suite — 전체 통과만 요구한다. "
                           "그 기능을 검증하는 테스트가 없어도 통과한다")
    return "protected", (f"증거 수준 {config.EVIDENCE_LEVEL} — 기능 ID 를 인용하는 "
                         "통과 테스트를 요구한다")


def check_run_logging(ctx: Context) -> tuple[str, str]:
    """TS-009 — 판정 기록이 남는가 (남지 않으면 사후 측정이 맹점이 된다)."""
    log = ctx.harness_root / "harness_runtime.log"
    if not log.is_file():
        return "unknown", ("실행 기록이 없다 — 아직 판정을 돌리지 않았거나 "
                           "`--no-log` 로 껐다. 기록이 없으면 집계가 '기록 없음'을 보고한다")
    return "protected", f"판정 기록이 쌓이고 있다 ({log.name})"


def check_tokenless_isolation(ctx: Context) -> tuple[str, str]:
    """TS-010 — 토큰 없는 경로가 유료 의존성을 import 하는가."""
    paid = ("langchain", "langgraph", "google.generativeai")
    loaded = [m for m in paid if any(k == m or k.startswith(m + ".") for k in sys.modules)]
    if loaded:
        return "exposed", (f"토큰 없는 경로에서 {', '.join(loaded)} 가 import 됐다 — "
                           "유료 의존성 없이 돌아야 한다")
    return "protected", "유료 의존성이 import 되지 않았다 (표준 라이브러리로 동작한다)"


def check_declared_commands(ctx: Context) -> tuple[str, str]:
    """TS-012 — 프로젝트가 광고하는 명령이 실제로 도는지 아무도 확인하지 않는가.

    '선언됐다'는 기계로 센다. '실제로 돈다'는 **돌려봐야** 안다 — 이 명령은
    돌리지 않으므로 `unknown` 이다. 그것을 `protected` 로 적으면 TS-012 가 그대로
    재발한다 (선언을 보고 동작한다고 가정한 것이 그 결함이었다).
    """
    import json

    pkg = ctx.root / "package.json"
    if not pkg.is_file():
        return "n/a", "package.json 이 없다 — 광고된 npm 명령이 없다"
    try:
        scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {})
    except (json.JSONDecodeError, OSError) as exc:
        return "unknown", f"package.json 을 읽을 수 없다: {exc}"
    if not scripts:
        return "n/a", "선언된 npm 명령이 없다"
    return "unknown", (
        f"명령 {len(scripts)}개가 선언돼 있다 ({', '.join(sorted(scripts)[:5])}"
        f"{' …' if len(scripts) > 5 else ''}). **이 명령이 실제로 도는지는 "
        "돌려봐야 안다** — CI 에서 전부 실행하는지 확인할 것 (TS-012 는 3개가 "
        "전부 깨져 있었다)"
    )


def check_target_app_defect(ctx: Context) -> tuple[str, str]:
    """TS-011 — 피험체 앱의 결함. 하네스의 실패 모드가 아니다."""
    return "n/a", ("피험체 앱의 구현 결함이며 하네스의 실패 모드가 아니다 — "
                   "임의 프로젝트에 대해 기계로 물을 수 있는 조건이 없다")


def check_evidence_independence(ctx: Context) -> tuple[str, str]:
    """TS-013/020 — 테스트가 검증 대상의 구조를 자기가 공급하는가."""
    from harness import independence

    colls = independence.declared_collections(ctx.root, ctx.cfg)
    if not colls:
        return "n/a", ("앱이 단일 출처로 선언한 컬렉션이 없다 — 자급 판정의 대상이 없다 "
                       "(대문자 이름 + 문자열 2개 이상)")
    res = independence.audit_independence(str(ctx.root), ctx.features)
    bad = [r for r in res if r.grade == "self-supplied"]
    if bad:
        return "exposed", (f"자급 {len(bad)}건 — 테스트가 앱의 선언을 손으로 복사했고 "
                           f"교차 검증 채널이 없다: {', '.join(r.feature_id for r in bad)}")
    single = [r for r in res if r.grade == "single-channel"]
    note = f"컬렉션 {len(colls)}개를 감시한다"
    if single:
        note += f" · 단일채널 {len(single)}건 (`cli independence` 로 확인)"
    return "protected", note


def check_tag_targets(ctx: Context) -> tuple[str, str]:
    """TS-014 — 태그가 존재하지 않는 기능을 가리키는가."""
    if not ctx.tag_ids:
        return "exposed", "태그된 테스트가 없다 — 게이트가 모든 기능을 거부한다"
    known = {str(f.get("id")) for f in ctx.features}
    ghosts = sorted(ctx.tag_ids - known)
    if ghosts:
        return "exposed", f"명세에 없는 ID 를 가리키는 태그: {', '.join(ghosts[:5])}"
    return "protected", (f"태그 {len(ctx.tag_ids)}개가 전부 명세의 기능을 가리킨다 "
                         "(`cli tags` 가 매 CI 마다 차단한다)")


def check_orphan_code(ctx: Context) -> tuple[str, str]:
    """TS-015/019 — 참조가 끊긴 코드가 남아 있는가."""
    orphans = [f for f in ctx.audit() if f.kind != "dead-config"]
    if orphans:
        return "exposed", f"고아 코드·미사용 임포트 {len(orphans)}건 — `cli deadcode` 로 확인"
    return "protected", "고아 코드 0건"


def check_coverage_gate(ctx: Context) -> tuple[str, str]:
    """TS-016 — 아무것도 실행하지 않는 테스트가 증거로 계수되는가."""
    if not config.REQUIRE_EVIDENCE_COVERAGE:
        return "exposed", ("HARNESS_REQUIRE_EVIDENCE_COVERAGE=false — 공허한 테스트가 "
                           "완벽한 증거로 계수된다")
    return "protected", "커버리지 요구가 켜져 있다 (증거가 소스를 1줄 이상 실행해야 한다)"


def check_own_config(ctx: Context) -> tuple[str, str]:
    """TS-017 — 프로젝트가 자기 규약을 선언했는가, 아니면 하네스 기본에 의존하는가."""
    from harness.project import CONFIG_NAME

    own = ctx.root / CONFIG_NAME
    if own.is_file():
        return "protected", f"프로젝트가 자기 규약을 선언했다 ({CONFIG_NAME})"
    return "exposed", (
        f"{CONFIG_NAME} 이 없어 **하네스의 기본값**이 적용된다 — 런너 "
        f"'{ctx.cfg.runner}', 단위 규약 {ctx.cfg.unit_suffixes}. 이 프로젝트의 "
        "실제 규약과 다르면 게이트가 틀린 판정을 낸다. `cli init` 으로 검수해 생성할 것"
    )


def check_paid_path_smoke(ctx: Context) -> tuple[str, str]:
    """TS-018 — 유료 경로가 검증 없이 방치되는가."""
    return _paid_path_in_use(ctx)


def check_mutation_validity(ctx: Context) -> tuple[str, str]:
    """TS-021 — 구문을 파괴한 변이가 '잡음'으로 계수되는가.

    정적 검사 커맨드가 없으면 `_typechecks` 는 True 를 돌려 **건너뛴다.** 그러면
    구문이 깨져서 테스트가 실패한 것을 '테스트가 잡았다'로 센다 — 돌연변이 점수가
    과대평가된다. 픽스처(vitest·pytest)는 `typecheck: []` 이므로 실제로 노출이다.
    """
    if not ctx.cfg.typecheck:
        return "exposed", (
            "정적 검사 커맨드가 선언되지 않았다 (`typecheck: []`). 변이가 구문을 "
            "파괴해 테스트가 실패해도 '테스트가 잡았다'로 계수된다 — 돌연변이 점수가 "
            "**과대평가**된다. `.harness.json` 의 `typecheck` 에 커맨드를 넣을 것"
        )
    return "protected", f"정적 검사로 변이 유효성을 확인한다: {' '.join(ctx.cfg.typecheck)}"


def check_mutation_reach(ctx: Context) -> tuple[str, str]:
    """TS-022 — 변이 표본이 같은 곳만 보는가 (예산 < 후보 수)."""
    from harness.mutate import MAX_MUTANTS_PER_FILE

    return "protected", (
        f"후보를 전부 모은 뒤 등간격으로 뽑는다 (파일당 예산 {MAX_MUTANTS_PER_FILE}). "
        "예산으로 건너뛴 수는 보고서가 `후보 n곳 중 m곳 시도` 로 적는다"
    )


def check_spec_names_members(ctx: Context) -> tuple[str, str]:
    """TS-023 — 생존한 변이를 명세가 요구하지 않는데 '증거의 공백'으로 읽는가."""
    from harness import independence

    colls = independence.declared_collections(ctx.root, ctx.cfg)
    if not colls:
        return "n/a", "컬렉션 선언이 없다 — 멤버 제거 변이의 대상이 없다"
    return "protected", ("컬렉션 멤버 제거 변이는 **명세가 그 멤버를 지목하는지** 보고 "
                         "`survived` 와 `out-of-spec` 으로 나눈다")


def check_published_numbers(ctx: Context) -> tuple[str, str]:
    """TS-024 — 발표된 수치가 측정과 어긋나 있는가.

    `docs/status.md` 는 **하네스 레포가 자기 대상에 대해** 생성하는 파일이다.
    임의의 프로젝트를 진단할 때 그 파일과 비교하면 당연히 어긋나고, 그것을
    '노출'로 적으면 거짓 양성이다 (픽스처 진단에서 실측으로 확인했다).

    그래서 먼저 **같은 질문이 성립하는지** 본다. 진단 대상이 하네스 자신의
    선언된 대상일 때만 드리프트를 묻고, 그 밖에는 `unknown` 이다 — 외부
    프로젝트가 수치를 발표하는지, 그것을 생성 파일로 관리하는지는 기계로 물을
    수 없다. `n/a` 로 적지 않는 이유: 그 실패는 외부 프로젝트에서도 **가능하다.**
    묻지 못한 것을 '발생하지 않는다'로 바꾸면 안 된다 (TS-016).
    """
    # `config_for` 는 target 을 **넘긴 경로로 덮어쓴다** (TS-025 의 격리 규칙).
    # 그래서 '하네스가 선언한 대상'을 알려면 `load` 를 써야 한다 — `config_for` 로
    # 물으면 항상 자기 자신이 나와 비교가 무의미해진다 (실측으로 확인했다).
    from harness.project import load

    own_cfg, _ = load(ctx.harness_root, detect_if_missing=False)
    try:
        declared = Path(own_cfg.target)
        if not declared.is_absolute():
            declared = ctx.harness_root / declared
        same = declared.resolve() == ctx.root
    except OSError:
        same = False
    if not same:
        return "unknown", (
            "docs/status.md 는 하네스가 **자기 대상**에 대해 생성하는 파일이므로 이 "
            "프로젝트에 대해서는 비교할 대상이 없다. 이 프로젝트가 수치를 산문에 "
            "박아 두고 있는지는 사람이 봐야 한다 — 박아 두었다면 생성 파일로 옮길 것"
        )
    if not (ctx.harness_root / "docs" / "status.md").is_file():
        return "exposed", "docs/status.md 가 없다 — 살아 있는 수치를 둘 곳이 없다"

    # **드리프트를 여기서 재계산하지 않는다** (TS-030).
    #
    # 이전 구현은 `status.check()` 를 불렀고, 그것이 `collect()` → **jest 실행 + 검수
    # + 독립성**을 돌려 호출당 약 25초였다. `diagnose()` 를 여러 번 부르는 검증
    # 스크립트에서 분 단위로 번졌고 `repro_ts027` 이 타임아웃했다.
    #
    # 그리고 **같은 사실을 두 곳에서 계산하는 것**이기도 했다 — `cli status --check`
    # 와 `repro_ts024` 가 이미 드리프트를 막는다. 두 곳에서 계산하면 둘이 어긋날 수
    # 있다는 것이 TS-024 의 교훈이다.
    #
    # 노출 진단이 물어야 하는 것은 "지금 어긋났는가"가 아니라 **"어긋남을 막는 장치가
    # 있는가"** 다. 그것은 CI 설정 한 줄을 읽으면 된다.
    ci = ctx.harness_root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    if "status --check" not in ci_text:
        return "exposed", (
            "생성 파일은 있으나 **CI 가 `cli status --check` 를 돌리지 않는다** — "
            "측정 코드가 바뀌면 문서가 조용히 거짓이 된다 (TS-024 가 터진 그 모양)"
        )
    return "protected", (
        "살아 있는 수치가 생성 파일에만 있고 CI 가 `cli status --check` 로 드리프트를 "
        "차단한다 (현재 일치 여부는 그 명령이 판정한다 — 여기서 다시 계산하지 않는다)"
    )


def check_runner_verified(ctx: Context) -> tuple[str, str]:
    """TS-025 — 이 프로젝트의 **모양**이 검증된 적 있는가.

    하드코딩한 목록이 아니라 픽스처와 CI 의 실제 구성에서 읽는다. 런너 실행 계층을
    CI 가 돌리는 것은 jest 뿐이고, 정적 계층은 픽스처가 있는 런너까지다.
    """
    runner = ctx.cfg.runner
    fixtures = ctx.harness_root / "verification" / "fixtures"
    # 픽스처가 선언한 런너 집합 — 정적 계층이 검증된 모양이다
    static_ok: set[str] = set()
    if fixtures.is_dir():
        import json

        for p in sorted(fixtures.glob("*/.harness.json")):
            try:
                static_ok.add(json.loads(p.read_text(encoding="utf-8")).get("runner", ""))
            except (json.JSONDecodeError, OSError):
                continue
    # 런너를 **실행**하는 계층은 CI 가 실제로 돌리는 것만 — 워크플로에서 읽는다
    ci = ctx.harness_root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    exec_ok = {r for r in ("jest", "vitest", "pytest") if f"npx {r}" in ci_text}

    if runner in exec_ok:
        return "protected", f"{runner} 는 정적·실행 계층 모두 CI 가 돌린다"
    if runner in static_ok:
        return "exposed", (
            f"{runner} 는 **정적 계층만** 검증됐다 (픽스처가 있다). 런너를 실제로 "
            f"실행하는 계층 — 테스트 결과 파싱·커버리지 측정 — 은 CI 에서 돌지 않는다. "
            f"현재 실행 계층이 CI 에 있는 런너: {', '.join(sorted(exec_ok)) or '없음'}"
        )
    return "exposed", (
        f"{runner} 는 픽스처도 CI 도 없다 — 이 모양은 **한 번도 검증되지 않았다.** "
        f"TS-025 는 두 번째 모양에 닿자마자 결함 5개가 나온 기록이다"
    )


def check_mutation_line_map(ctx: Context) -> tuple[str, str]:
    """TS-026 — 증거가 지나가지 않는 줄에 변이를 넣는가.

    줄 지도를 만들 수 있는지는 **런너를 돌려야** 알지만, 리포터 플래그가 선언돼
    있는지는 물을 수 있다. 플래그가 없으면 줄 지도가 없고, 그러면 미실행 줄
    필터가 작동하지 않는다.
    """
    from harness.verify import runner_for

    try:
        runner = runner_for(str(ctx.root))
    except ValueError as exc:
        return "unknown", f"런너를 결정할 수 없어 묻지 못했다: {exc}"
    if runner.name == "pytest":
        return "protected", "pytest-cov 가 executed_lines 를 직접 준다 (환산 불필요)"
    flags = " ".join(runner._coverage_flags("/tmp"))
    if "reporter=json " in flags + " " or flags.endswith("=json"):
        pass
    if "=json" not in flags.replace("=json-summary", ""):
        return "exposed", ("커버리지 리포터가 줄 지도를 만들지 않는다 — 미실행 줄에 "
                           "변이가 들어가고 그 생존이 증거의 구멍으로 계수된다")
    return "protected", "커버리지 리포터가 줄 지도를 만든다 (미실행 줄을 변이에서 제외한다)"


def check_draft_quality(ctx: Context) -> tuple[str, str]:
    """TS-028 — 명세 초안을 뽑을 **선언**이 이 프로젝트에 있는가.

    초안은 상태 조건부 선언(`disabled={…}`)과 검증 제약(`required`)에서만 나온다.
    그런 선언이 없는 프로젝트에서는 초안이 0건이고, 그것은 결함이 아니라 **조건**이다
    — 명세를 전부 손으로 써야 한다는 뜻이므로 알려줄 가치가 있다.
    """
    from harness.draft import extract_declarations

    try:
        decls = extract_declarations(ctx.root, ctx.cfg)
    except OSError as exc:
        return "unknown", f"선언을 읽지 못했다: {exc}"
    if not decls:
        return "exposed", (
            "뽑을 상태 조건부 선언이 없다 (`disabled={…}`·`aria-invalid={…}`·"
            "`required` 등). 명세 초안이 0건이므로 **명세를 전부 손으로 써야 한다** — "
            "`cli inspect` 의 질문 목록이 어디를 적어야 하는지는 알려준다"
        )
    kinds = {d.rule_kind for d in decls}
    return "protected", (
        f"선언 {len(decls)}건에서 초안을 뽑을 수 있다 "
        f"({'·'.join(sorted(kinds))}) — `cli inspect --write-draft`"
    )


def check_language_matrix(ctx: Context) -> tuple[str, str]:
    """TS-030 — 계층별 지원 차이가 **읽을 수 있게** 드러나 있는가.

    두 가지를 묻는다:
      1. 모든 런너에 **피험체**(픽스처 또는 주 대상)가 있는가 — 없으면 그 모양은
         한 번도 검증된 적이 없고, 그 사실이 표에 드러나야 한다 (TS-025).
      2. 이 프로젝트가 쓰는 런너의 지원 계층이 어디까지인가.

    표 자체는 `docs/status.md` 가 **생성**하고 `cli status --check` 가 드리프트를
    막는다. 여기서는 그 표가 담을 **사실**을 검사한다.
    """
    from harness.status import language_support

    try:
        rows = language_support(ctx.harness_root)
    except (OSError, ValueError) as exc:
        return "unknown", f"지원 현황을 읽지 못했다: {exc}"
    if not rows:
        return "unknown", "런너 목록을 읽지 못했다"

    orphan = [r["runner"] for r in rows if not r["subject"]]
    if orphan:
        return "exposed", (
            f"피험체가 없는 런너 {len(orphan)}개: {', '.join(orphan)} — 그 모양은 "
            "한 번도 검증된 적이 없다. `verification/fixtures/` 에 픽스처를 둘 것 "
            "(docs/adding-a-language.md)"
        )
    mine = next((r for r in rows if r["runner"] == ctx.cfg.runner), None)
    if mine is None:
        return "exposed", (
            f"'{ctx.cfg.runner}' 런너 클래스가 없다 — `harness/runner.py` 에 "
            "서브클래스를 추가할 것 (docs/adding-a-language.md)"
        )
    gaps = [label for label, key in (("CI 실행", "runs_in_ci"), ("초안", "draft"),
                                     ("컬렉션", "collections"), ("검수", "inspect"))
            if not mine[key]]
    if mine["mutation_hits"] == 0:
        gaps.append("변이(연산자가 이 언어에 0곳 매칭)")
    if gaps:
        return "exposed", (
            f"{ctx.cfg.runner} 는 이 계층이 동작하지 않는다: {', '.join(gaps)}. "
            "게이트(태그·커버리지)는 돌지만 그 위 칸은 비어 있다 — "
            "docs/status.md 의 지원 표가 이것을 생성해 싣는다"
        )
    return "protected", (
        f"{ctx.cfg.runner} 는 모든 계층이 동작한다 (변이 {mine['mutation_hits']}곳 매칭). "
        f"런너 {len(rows)}개 전부 피험체가 있다"
    )


def check_advisory_split(ctx: Context) -> tuple[str, str]:
    """TS-029 — 차단하는 판정에 **맹점 있는 검사**가 섞여 있는가.

    맹점 있는 판정을 차단 자리에 놓으면 오탐이 CI 를 영구히 빨간불로 만들고,
    그 압력이 `|| true` 를 낳아 **같은 명령 안의 정확한 판정까지** 꺼진다.
    """
    try:
        report = ctx.report()
    except (OSError, ValueError) as exc:
        return "unknown", f"검수를 돌리지 못했다: {exc}"
    blocking = [c for c in report.checks if c.auto and c.verdict == "violated"]
    advisory = [c for c in report.checks if c.verdict == "advisory"]

    ci = ctx.harness_root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    if "cli inspect || true" in ci_text:
        return "exposed", (
            "CI 가 `cli inspect || true` 로 **종료 코드를 버린다** — 검수가 돌지만 "
            "아무것도 막지 못한다. 맹점 있는 판정은 `advisory` 로 내리고 `|| true` 를 뗄 것"
        )
    if blocking:
        return "exposed", (
            f"차단하는 위반 {len(blocking)}건이 있다: "
            f"{', '.join(c.kind for c in blocking)} — 고치거나, 맹점이 있는 판정이라면 "
            "`advisory` 로 내릴 것"
        )
    return "protected", (
        f"위반 0 · 권고 {len(advisory)} — 맹점 있는 판정은 차단하지 않고, "
        "맹점 없는 판정(죽은 스크립트·라우트 누락)은 CI 가 막는다"
    )


def check_exposure_declarations(ctx: Context) -> tuple[str, str]:
    """TS-027 — 실패 모드 기록이 **질의 가능한가.**

    자기 참조적이지만 순환은 아니다. 이 검사기는 "노출 진단 자체가 완전한가"를
    묻는다 — 모든 TS 문서가 `exposure:` 를 선언했고 선언된 키에 검사기가 있는가.
    그 둘이 어긋나면 **다른 모든 판정이 불완전하다.**

    `diagnose()` 를 다시 부르지 않는다 (무한 재귀가 된다). 선언 집합과 검사기
    집합을 직접 비교한다 — 그것이 어긋남의 전부다.
    """
    modes = load_modes()
    if not modes:
        return "exposed", "TS 문서를 읽지 못했다 — 노출 진단이 아무것도 묻지 못한다"
    no_key = [m.ts_id for m in modes if not m.exposure_key]
    declared = {m.exposure_key for m in modes if m.exposure_key}
    missing = sorted(declared - set(CHECKS))
    orphans = sorted(set(CHECKS) - declared)
    if no_key or missing or orphans:
        parts = []
        if no_key:
            parts.append(f"`exposure:` 미선언 {len(no_key)}건 ({', '.join(no_key[:3])})")
        if missing:
            parts.append(f"검사기 없는 키 {len(missing)}개 ({', '.join(missing[:3])})")
        if orphans:
            parts.append(f"고아 검사기 {len(orphans)}개 ({', '.join(orphans[:3])})")
        return "exposed", " · ".join(parts) + " — 다른 판정이 불완전하다"
    return "protected", (
        f"실패 모드 {len(modes)}건이 전부 `exposure:` 를 선언했고 검사기 "
        f"{len(CHECKS)}개가 전부 어떤 문서에 묶여 있다 — `cli exposure` 가 "
        "어긋남을 종료 코드 1 로 차단한다"
    )


#: 검사기 등록부 — 키는 TS 문서의 `exposure:` 가 선언한다.
#: 이 표에 없는 키를 문서가 선언하면 `cli exposure` 가 그 사실을 보고한다.
#: 반대로 이 표에만 있고 아무 문서도 선언하지 않으면 **고아 검사기**로 보고한다.
CHECKS: dict[str, Callable[[Context], tuple[str, str]]] = {
    "spec-path": check_spec_path,
    "console-encoding": check_console_encoding,
    "paid-path-exit": check_paid_path_exit,
    "paid-path-quota": check_paid_path_quota,
    "test-evidence-gate": check_test_evidence_gate,
    "dead-config": check_dead_config,
    "evidence-level": check_evidence_level,
    "run-logging": check_run_logging,
    "tokenless-isolation": check_tokenless_isolation,
    "declared-commands": check_declared_commands,
    "target-app-defect": check_target_app_defect,
    "evidence-independence": check_evidence_independence,
    "tag-targets": check_tag_targets,
    "orphan-code": check_orphan_code,
    "coverage-gate": check_coverage_gate,
    "own-config": check_own_config,
    "paid-path-smoke": check_paid_path_smoke,
    "mutation-validity": check_mutation_validity,
    "mutation-reach": check_mutation_reach,
    "spec-names-members": check_spec_names_members,
    "published-numbers": check_published_numbers,
    "runner-verified": check_runner_verified,
    "mutation-line-map": check_mutation_line_map,
    "exposure-declarations": check_exposure_declarations,
    "draft-quality": check_draft_quality,
    "advisory-split": check_advisory_split,
    "language-matrix": check_language_matrix,
}


# ── 진단 ─────────────────────────────────────────────────────────────────────

def build_context(project_root: str | Path, harness_root: str | Path) -> Context:
    """검사기가 공유할 사실을 한 번에 모은다."""
    from harness import tags
    from harness.verify import load_features

    root = Path(project_root).resolve()
    cfg = config_for(root)
    try:
        features = load_features(str(root))
    except (OSError, ValueError):
        features = []
    try:
        tag_ids = {r.feature_id for r in tags.scan_tags(str(root), cfg)}
    except (OSError, ValueError):
        tag_ids = set()
    return Context(root=root, harness_root=Path(harness_root).resolve(),
                   cfg=cfg, features=features, tag_ids=tag_ids)


def validate_declarations(modes: list[FailureMode]) -> tuple[list[str], list[str]]:
    """선언 자체의 어긋남만 검사한다. (검사기 없는 선언, 선언되지 않은 검사기)

    **`diagnose()` 에서 떼어 냈다** (TS-030). 선언 검증은 frontmatter 를 읽는 일이라
    밀리초면 끝나는데, `diagnose()` 안에 있으면 검증하려고 **jest·검수·독립성까지**
    돌려야 했다. 실측에서 `repro_ts027` 이 3분 42초가 됐다.

    테스트가 비싼 경로 없이 이것만 부를 수 있어야 한다 — 그러지 않으면 검증 비용이
    CI 에서 감당 못 할 수준으로 커지고, 그러면 검증을 줄이는 압력이 생긴다.
    """
    missing: list[str] = []
    for mode in modes:
        if mode.resolution not in ("build", "use", "accept"):
            missing.append(
                f"{mode.ts_id} ({mode.doc}) 의 `resolution:` 이 "
                f"build/use/accept 중 하나가 아니다 (현재: {mode.resolution!r})")
        if not mode.exposure_key:
            missing.append(f"{mode.ts_id} ({mode.doc}) 가 `exposure:` 를 선언하지 않았다")
        elif mode.exposure_key not in CHECKS:
            missing.append(
                f"{mode.ts_id} 가 선언한 `exposure: {mode.exposure_key}` 에 검사기가 없다")
    declared = {m.exposure_key for m in modes if m.exposure_key}
    return missing, sorted(set(CHECKS) - declared)


def diagnose(project_root: str | Path,
             harness_root: str | Path,
             troubleshooting_dir: str | Path | None = None
             ) -> tuple[list[Verdict], list[str], list[str]]:
    """전수 진단.

    Returns:
        (판정 목록, 검사기 없는 선언, 선언되지 않은 검사기)

        뒤의 두 목록이 **양방향 강제**다. 비어 있지 않으면 문서와 코드가 어긋났다는
        뜻이고, `cli exposure` 가 그것을 먼저 보고한다 — 선언 누락이 '해당 없음'으로
        위장되는 것을 막는다 (TS-007·019 의 죽은 설정과 같은 구조).
    """
    modes = load_modes(troubleshooting_dir)
    missing_checks, orphan_checks = validate_declarations(modes)
    ctx = build_context(project_root, harness_root)

    verdicts: list[Verdict] = []
    for mode in modes:
        if not mode.exposure_key:
            verdicts.append(Verdict(mode, "unknown", "노출 조건이 선언되지 않았다"))
            continue
        fn = CHECKS.get(mode.exposure_key)
        if fn is None:
            verdicts.append(Verdict(mode, "unknown",
                                    f"검사기 '{mode.exposure_key}' 가 구현되지 않았다"))
            continue
        try:
            status_, detail = fn(ctx)
        except Exception as exc:                      # 검사기 자신의 결함
            status_, detail = "unknown", f"검사기가 예외를 던졌다: {type(exc).__name__}: {exc}"
        verdicts.append(Verdict(mode, status_, detail))

    return verdicts, missing_checks, orphan_checks


def render(verdicts: list[Verdict], missing: list[str], orphans: list[str],
           project_root: str, show_all: bool = False) -> str:
    """사람이 읽는 보고."""
    bar = "=" * 72
    counts = {k: 0 for k in ("exposed", "protected", "n/a", "unknown")}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1

    lines = [
        bar,
        f"노출 진단 — {project_root} 이 어떤 실패 모드에 노출되어 있는가",
        bar,
        "",
        "  기록된 실패 모드를 **터지기 전에** 이 프로젝트에 대해 묻는다.",
        "  점수가 아니라 사실이다 — 각 항목은 기계로 확인한 조건 하나를 말한다.",
        "",
        f"  노출 {counts['exposed']} · 보호됨 {counts['protected']} · "
        f"해당없음 {counts['n/a']} · 확인불가 {counts['unknown']}",
    ]

    # 문서와 코드의 어긋남을 **먼저** 보고한다 — 이것이 있으면 위 수치가 불완전하다
    if missing or orphans:
        lines += ["", "  " + "-" * 68, "  ⚠ 선언과 검사기가 어긋난다 — 위 수치는 불완전하다"]
        for m in missing:
            lines.append(f"    · {m}")
        for o in orphans:
            lines.append(f"    · 검사기 '{o}' 를 아무 TS 문서도 선언하지 않았다 (고아 검사기)")

    for group, label in (("exposed", "노출 — 이 프로젝트에서 발생할 수 있다"),
                         ("unknown", "확인 불가 — 사람이 봐야 한다"),
                         ("protected", "보호됨 — 가드가 작동한다"),
                         ("n/a", "해당 없음 — 이 모양에서는 발생하지 않는다")):
        rows = [v for v in verdicts if v.status == group]
        if not rows:
            continue
        if group in ("protected", "n/a") and not show_all:
            lines += ["", f"  {label}: {len(rows)}건 (`--all` 로 전부 출력)"]
            continue
        lines += ["", "  " + "-" * 68, f"  {label}", ""]
        for v in rows:
            lines.append(f"  [{v.mark()}] {v.mode.ts_id}  {v.mode.short()}")
            lines.append(f"            {v.detail}")
            if v.mode.guard and group in ("exposed", "unknown"):
                lines.append(f"            가드: {v.mode.guard}")

    # 루프를 끊는 사실 판정 (TS-030) — 노출된 것 중 **더 만들어야** 하는 것의 수.
    # 0 이면 도구를 더 만들 이유가 없다. 남은 노출은 써보거나 받아들이는 것이다.
    by_build = [v for v in verdicts if v.status == "exposed" and v.mode.resolution == "build"]
    by_use = [v for v in verdicts if v.status == "exposed" and v.mode.resolution == "use"]
    by_accept = [v for v in verdicts if v.status == "exposed" and v.mode.resolution == "accept"]
    lines += ["", "  " + "-" * 68, "  노출된 것은 무엇으로 해결되는가"]
    lines.append(f"    더 만들어야 (build)  {len(by_build)}건"
                 + ("".join(f"  {v.mode.ts_id}" for v in by_build) if by_build else ""))
    lines.append(f"    써봐야 (use)         {len(by_use)}건"
                 + ("".join(f"  {v.mode.ts_id}" for v in by_use) if by_use else ""))
    lines.append(f"    받아들임 (accept)    {len(by_accept)}건"
                 + ("".join(f"  {v.mode.ts_id}" for v in by_accept) if by_accept else ""))
    if not by_build:
        lines.append("    → **도구를 더 만들 이유가 없다.** 남은 것은 쓰거나 받아들이는 것이다")
    else:
        lines.append("    → 아직 만들 것이 남았다 (위 build 항목)")

    lines += [
        "",
        "  " + "-" * 68,
        "  '확인 불가' 를 '해당 없음' 으로 읽지 말 것 — 묻지 못한 것과 발생하지",
        "  않는 것은 다른 사실이다 (TS-016).",
        bar,
    ]
    return "\n".join(lines)

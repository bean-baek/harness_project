"""
harness/status.py
─────────────────
**살아 있는 측정값을 생성한다 — 산문에 박아 넣지 않는다.**

왜 필요한가 (TS-024):
  README 가 같은 측정값을 **네 번 다르게** 발표했다. 이틀 사이다.

    a53966f  F-005 돌연변이 점수 50%   (잡음 2 / 생존 2 / 폐기 2)
    fed5ac1                    40%   (잡음 2 / 생존 3 / 폐기 0)
    6d66152                    33%   (잡음 5 / 생존 10 / 타입 1)
    5189a3d                    50%   (잡음 3 / 생존 3 / 명세밖 3)

  매번 측정 코드를 고쳤고, 매번 README 의 수치를 손으로 갱신했고, 한 번은 **갱신을
  빠뜨려 33% 와 50% 가 같은 문서에 동시에** 들어 있었다. 측정 코드가 바뀌면 산문의
  수치는 즉시 거짓이 되는데 **아무도 모른다.**

  이것은 **죽은 설정과 같은 구조**다 (TS-007/TS-019) — 문서가 값을 주장하고 코드가
  그것을 모른다. 그 패턴은 이미 `deadcode.py` 로 기계화해 막았다. 같은 처방을 쓴다.

처방:
  살아 있는 측정값은 **생성 파일**(`docs/status.md`)에만 둔다. `cli status` 가 만들고
  `cli status --check` 가 재생성해 커밋된 내용과 다르면 **실패**한다. CI 가 그것을 돌린다.
  락파일 검사와 같은 방식이고, 오탐이 구조적으로 불가능하다 — 같은 입력에서 같은
  문자열이 나오는지만 본다.

무엇을 담지 않는가:
  **비싼 측정은 값을 발표하지 않는다.** 돌연변이는 기능당 약 47초여서 매 CI 에
  돌릴 수 없고, 돌리지 않으면 검증되지 않은 수치가 된다. 그래서 값 대신
  **산출 명령**을 적는다 (`cli mutate <기능>`).

  회귀 검증 건수도 같은 이유로 넣지 않는다 — 전부 돌리면 분 단위다. CI 가 스크립트
  각각의 종료 코드를 이미 확인하므로 '총 n건'이라는 수치는 검증 없이 떠다니는 값이었다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.project import SKIP_DIRS, load, walk_files

#: 생성 파일 경로 (하네스 루트 기준)
STATUS_PATH = "docs/status.md"

#: 생성 파일 머리말 — 손으로 고치지 말라는 경고를 파일 자신이 들고 있어야 한다
_HEADER = """<!-- 이 파일은 `python -m harness.cli status` 가 생성한다. 손으로 고치지 말 것. -->
<!-- CI 가 `cli status --check` 로 재생성해 diff 가 있으면 실패한다 (TS-024). -->

# 현재 측정값

살아 있는 수치는 여기에만 둔다. README 의 산문에 박아 넣으면 측정 코드가 바뀔 때
조용히 거짓이 된다 — 실제로 같은 값이 네 번 다르게 발표됐다 (TS-024).

재생성: `python -m harness.cli status`
"""


def collect(project_root: str, harness_root: str | Path = ".") -> dict[str, Any]:
    """살아 있는 측정값을 모은다.

    실측 비용 (웜 캐시): 판별력 9.3초 + 검수 10.4초 + 자기 감사 4.0초 +
    독립성 2.5초 ≈ **26초**. CI 에 한 번 추가하기에는 허용 범위이고, 돌연변이
    (기능당 47초)는 그 선을 넘으므로 값을 싣지 않는다.

    이 주석의 수치도 시점 측정이다 — 늘어나면 `--check` 가 아니라 사람이 알아채야
    한다. 그래서 '빠르다'가 아니라 **숫자**로 적는다 (TS-024 의 교훈).
    """
    from harness import deadcode, independence
    from harness import inspect as inspect_mod
    from harness.metrics import discrimination_report
    from harness.verify import load_features

    out: dict[str, Any] = {}

    features = load_features(project_root)
    out["features_total"] = len(features)
    out["features_passing"] = sum(1 for f in features if f.get("passes"))

    # 판별력 — jest 를 한 번만 돌려 모든 수준이 공유한다
    disc = discrimination_report(project_root, features)
    if "error" in disc:
        out["discrimination_error"] = disc["error"]
    else:
        out["suite_tests"] = disc.get("suite_total", 0)
        out["suite_failed"] = disc.get("suite_failed", 0)
        out["levels"] = {
            lvl: data["accepted"] for lvl, data in (disc.get("levels") or {}).items()
        }
        ab = disc.get("ab_suite_vs_feature") or {}
        out["discrimination"] = ab.get("discrimination")

    # 증거 독립성 (정적)
    grades: dict[str, int] = {}
    for r in independence.audit_independence(project_root, features):
        grades[r.grade] = grades.get(r.grade, 0) + 1
    out["independence"] = grades

    # 프로젝트 검수 — 자동 판정 위반 수 (정적)
    report = inspect_mod.inspect_project(harness_root)
    out["inspect_violated"] = sum(
        1 for c in report.checks if c.auto and c.verdict == "violated"
    )
    out["inspect_ok"] = sum(1 for c in report.checks if c.auto and c.verdict == "ok")
    out["inspect_needs_intent"] = sum(1 for c in report.checks if not c.auto)

    # 하네스 자기 감사 (정적)
    audit = deadcode.audit(harness_root)
    kinds: dict[str, int] = {}
    for f in audit:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    out["deadcode"] = kinds

    # 회귀 스크립트 **개수** — 건수는 넣지 않는다 (전부 돌리면 분 단위다)
    verification = Path(harness_root) / "verification"
    out["repro_scripts"] = len(sorted(verification.glob("repro_ts*.py")))
    out["failure_modes"] = len(sorted(
        (Path(harness_root) / "troubleshooting").glob("TS-*.md")
    ))

    out["languages"] = language_support(harness_root)

    return out


def language_support(harness_root: str | Path) -> list[dict[str, Any]]:
    """런너별로 **어느 계층이 실제로 동작하는가** — 코드에서 읽는다.

    손으로 적으면 계층이 늘 때 조용히 거짓이 된다 (TS-024). 그래서 표를 쓰지 않고
    `RUNNERS`·픽스처·CI·연산자 표를 **읽어서** 만든다.

    왜 이 표가 필요한가 (TS-025·TS-030): "모든 프로젝트에 붙는다"는 주장이 두 번째
    프로젝트에서 깨졌다. 계층별로 묶인 정도가 다르다 — 게이트는 런너만 있으면 돌고,
    돌연변이는 언어의 문법을 알아야 한다. 그 차이를 읽는 사람이 알 수 없었다.
    """
    import json

    from harness import draft, independence, mutate
    from harness import inspect as inspect_mod
    from harness.runner import RUNNERS

    root = Path(harness_root)

    # 픽스처가 선언한 런너 — 정적 계층이 검증된 모양이다
    fixtures: dict[str, str] = {}
    fx_dir = root / "verification" / "fixtures"
    if fx_dir.is_dir():
        for p in sorted(fx_dir.glob("*/.harness.json")):
            try:
                fixtures[json.loads(p.read_text(encoding="utf-8")).get("runner", "")] = p.parent.name
            except (json.JSONDecodeError, OSError):
                continue
    # 주 피험체가 쓰는 런너 (픽스처가 아니라 실제 앱)
    try:
        own, _ = load(root, detect_if_missing=False)
        subject_runner = own.runner
        subject_name = Path(own.target).name or "target"
    except (OSError, ValueError):
        subject_runner, subject_name = "", ""

    # CI 가 런너를 **실제로 실행**하는가
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8") if ci.is_file() else ""

    # 런너별 피험체 경로 — 확장자와 변이 매칭을 **그 프로젝트의 실제 파일에서** 읽는다
    subject_dir: dict[str, Path] = {}
    if subject_runner:
        subject_dir[subject_runner] = Path(own.target) if Path(own.target).is_absolute() \
            else (root / own.target)
    for runner_name, fixture_name in fixtures.items():
        subject_dir.setdefault(runner_name, fx_dir / fixture_name)

    out: list[dict[str, Any]] = []
    for name in sorted(RUNNERS):
        subject_path = subject_dir.get(name)
        # **하드코딩한 확장자 매핑을 쓰지 않는다** (TS-031). 처음 구현은
        # `{"jest": ".tsx", ...}` 딕셔너리를 두었고, 거기 없는 런너(`unittest`)는
        # 모든 계층이 `—` 로 나왔다 — 실제로는 검수·컬렉션이 동작하는데도.
        # **손으로 적은 표가 조용히 거짓이 되는 것을 막으려고 만든 표 안에서**
        # 같은 실수를 한 것이다. 피험체의 실제 소스 파일에서 확장자를 읽는다.
        exts: set[str] = set()
        hits = 0
        if subject_path and subject_path.is_dir():
            cfg_for_subject, _ = (load(subject_path, detect_if_missing=False)
                                  if (subject_path / ".harness.json").is_file()
                                  else (own, None))
            for d in (cfg_for_subject.source_dirs if cfg_for_subject else ["src"]):
                base = subject_path / d
                if not base.is_dir():
                    continue
                for f in walk_files(base, SKIP_DIRS)[:400]:
                    if f.suffix not in inspect_mod.SOURCE_EXTS                             and f.suffix not in draft.MARKUP_EXTS:
                        continue
                    if cfg_for_subject and cfg_for_subject.is_test_file(f.name):
                        continue
                    exts.add(f.suffix)
                    # 변이 매칭을 **모든 소스 파일에 걸쳐** 센다. 첫 파일 하나만
                    # 보면 어느 파일이 먼저 정렬되는지에 수치가 달라진다 —
                    # 손으로 적은 대표 구문만큼이나 임의적이다 (TS-031).
                    try:
                        src = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    hits += sum(len(mutate._candidate_lines(src, pat))
                                for _rule, pat, _rep in mutate.MUTATIONS)
        out.append({
            "runner": name,
            "subject": (subject_name if name == subject_runner
                        else fixtures.get(name, "")),
            "gate": True,                                   # 런너 클래스가 있으면 돈다
            # CI 가 이 런너를 **실제로 실행**하는가.
            #
            # 호출 형태를 추측하지 않는다 (TS-031). 하네스를 통해 돌리면 커맨드에
            # 런너 이름이 아예 안 나온다(`cli verify`). 그래서 CI 단계가 **선언**한다 —
            # 단계 이름에 `런너 실행 계층: <런너>` 를 넣으면 그것이 선언이다.
            # TS 문서의 `exposure:` 와 같은 방식이고, 선언이 없으면 `—` 로 **과소**
            # 보고한다 (없는 검증을 있다고 말하지 않는다).
            "runs_in_ci": (f"npx {name}" in ci_text
                           or f"런너 실행 계층: {name}" in ci_text),
            "draft": bool(exts & set(draft.MARKUP_EXTS)),
            "collections": bool(exts & set(independence._SOURCE_EXTS)),
            "inspect": bool(exts & set(inspect_mod.SOURCE_EXTS)),
            "mutation_hits": hits,
        })
    return out


# `unresolved_by_building()` 은 **만들었다가 지웠다** (TS-030).
#
# `status.collect` 에서 `exposure.diagnose` 를 부르면 그 안의
# `check_published_numbers` 가 다시 `status.check` → `collect` 를 불러 **무한 재귀**가
# 된다. 루프를 끊는 규칙을 만들면서 루프를 만든 것이고, 그게 이 결함의 기록이다.
#
# 그리고 중복이기도 했다 — `cli exposure` 의 출력이 이미 build/use/accept 를 센다.
# 같은 사실을 두 곳에서 계산하면 둘이 어긋날 수 있다(TS-024 의 모양). 한 곳에만 둔다.
#
# 교훈: 생성 파일은 **싼 측정만** 담는다. 다른 진단을 호출하는 측정은 생성 파일에
# 넣지 않는다 — 비용도 모르고 순환도 보이지 않는다.


def render(data: dict[str, Any]) -> str:
    """측정값을 마크다운으로. **같은 입력이면 같은 문자열**이어야 한다 (diff 검사용)."""
    lines = [_HEADER, "", "## 게이트", "", "| 측정 | 값 |", "|---|---|"]
    lines.append(f"| 기능 통과 | {data['features_passing']} / {data['features_total']} |")
    if "suite_tests" in data:
        lines.append(
            f"| 단위 스위트 | {data['suite_tests'] - data['suite_failed']}"
            f" / {data['suite_tests']} 통과 |"
        )
    levels = data.get("levels") or {}
    for lvl in ("suite", "feature", "step"):
        if lvl in levels:
            lines.append(
                f"| 증거 수준 `{lvl}` 통과 | {levels[lvl]} / {data['features_total']} |"
            )
    if data.get("discrimination") is not None:
        lines.append(f"| 판별력 (suite→feature) | {data['discrimination'] * 100:.1f}% |")
    if "discrimination_error" in data:
        lines.append(f"| 판별력 | 측정 실패: {data['discrimination_error'][:60]} |")

    lines += ["", "## 증거 독립성 (TS-020)", "", "| 등급 | 기능 수 |", "|---|---|"]
    labels = {
        "cross-checked": "교차검증 (채널 2개)",
        "single-channel": "단일채널",
        "self-supplied": "자급 (TS-013 의 모양)",
        "no-evidence": "증거 없음",
    }
    grades = data.get("independence") or {}
    for key, label in labels.items():
        lines.append(f"| {label} | {grades.get(key, 0)} |")

    lines += ["", "## 프로젝트 검수 (TS-017)", "", "| 항목 | 건수 |", "|---|---|"]
    lines.append(f"| 자동 판정 — 통과 | {data['inspect_ok']} |")
    lines.append(f"| 자동 판정 — 위반 | {data['inspect_violated']} |")
    lines.append(f"| 의도가 필요한 후보 | {data['inspect_needs_intent']} |")

    lines += ["", "## 하네스 자기 감사 (TS-019)", "", "| 검사 | 발견 |", "|---|---|"]
    dead = data.get("deadcode") or {}
    for kind, label in (("dead-config", "죽은 설정"), ("orphan", "고아 코드"),
                        ("unused-import", "미사용 임포트")):
        lines.append(f"| {label} | {dead.get(kind, 0)} |")

    # 언어 지원 — **손으로 적지 않는다.** 계층이 늘면 표가 조용히 거짓이 된다 (TS-024).
    langs = data.get("languages") or []
    if langs:
        lines += ["", "## 언어·런너 지원 (TS-030)", "",
                  "계층별로 묶인 정도가 다르다. 게이트는 런너 클래스 하나로 돌고,",
                  "돌연변이는 그 언어의 문법을 알아야 한다. 이 표는 코드에서 읽은 것이다.", "",
                  "| 런너 | 피험체 | 게이트 | CI 실행 | 검수 | 컬렉션 | 초안 | 줄 변이 |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in langs:
            mark = {True: "O", False: "—"}
            lines.append(
                f"| {r['runner']} | {r['subject'] or '없음'} | {mark[r['gate']]} "
                f"| {mark[r['runs_in_ci']]} | {mark[r['inspect']]} "
                f"| {mark[r['collections']]} | {mark[r['draft']]} "
                f"| {r['mutation_hits']}곳 |"
            )
        lines += ["",
                  "`줄 변이` 는 그 피험체의 **모든 소스 파일**에 줄 변이 연산자가",
                  "매칭되는 실측 개수다. 0 이면 줄 변이가 그 언어에서 아무것도 하지 않는다 —",
                  "`===`·`&&` 가 없고 `if` 에 괄호를 쓰지 않는 언어가 그렇다.",
                  "**컬렉션 멤버 제거 변이는 이 수치와 무관하게 동작한다** (파이썬에서도 된다).",
                  "새 언어를 붙이는 절차: [docs/adding-a-language.md](adding-a-language.md)"]


    lines += [
        "",
        "## 규모",
        "",
        "| | |",
        "|---|---|",
        f"| 회귀 검증 스크립트 | {data['repro_scripts']}개 |",
        f"| 기록된 실패 모드 | {data['failure_modes']}건 |",
        "",
        "## 여기에 없는 것 — 그리고 왜",
        "",
        "| 측정 | 산출 명령 | 값을 싣지 않는 이유 |",
        "|---|---|---|",
        "| 돌연변이 점수 | `cli mutate <기능>` | 기능당 약 47초. 매 CI 에 돌릴 수 없고, "
        "돌리지 않으면 **검증되지 않은 수치**가 된다 |",
        "| 회귀 검증 건수 | `python verification/repro_tsNNN.py` | 전부 돌리면 분 단위. "
        "CI 가 각 스크립트의 종료 코드를 이미 확인하므로 '총 n건'은 검증 없이 떠다니는 값이었다 |",
        "| 커버리지 % | `npm test` (web_target) | 임계 미달로 종료 코드가 1 이어서 "
        "통과/실패와 수치가 섞인다 (TS-012) |",
        "",
        "검증되지 않는 수치를 발표하지 않는 것이 이 파일의 목적이다.",
        "",
    ]
    return "\n".join(lines)


def write(project_root: str, harness_root: str | Path = ".") -> tuple[Path, str]:
    """생성해 파일에 쓴다. (경로, 내용)"""
    data = collect(project_root, harness_root)
    text = render(data)
    path = Path(harness_root) / STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, text


def check(project_root: str, harness_root: str | Path = ".") -> tuple[bool, str]:
    """재생성해 커밋된 내용과 비교한다. (일치 여부, 진단).

    락파일 검사와 같은 방식이다 — 같은 입력에서 같은 문자열이 나오는지만 보므로
    오탐이 구조적으로 불가능하다.
    """
    data = collect(project_root, harness_root)
    expected = render(data)
    path = Path(harness_root) / STATUS_PATH
    if not path.is_file():
        return False, f"{STATUS_PATH} 가 없습니다. `cli status` 로 생성하십시오."
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return True, ""

    import difflib

    diff = list(difflib.unified_diff(
        actual.splitlines(), expected.splitlines(),
        fromfile=f"{STATUS_PATH} (커밋된 내용)", tofile="(지금 측정한 값)", lineterm="",
    ))
    return False, (
        f"{STATUS_PATH} 가 현재 측정값과 다릅니다 — 문서가 거짓을 말하고 있습니다.\n"
        f"`python -m harness.cli status` 로 재생성해 커밋하십시오.\n\n"
        + "\n".join(diff[:40])
    )

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

    return out


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

"""
harness/metrics.py
──────────────────
하네스 **자체**를 측정한다 — 산출물이 아니라 장치의 성능을.

도입 근거 (revfactory/harness 비교 분석, docs/comparison-revfactory.md):
  해당 프로젝트의 스킬 검증 방법론은 두 가지 원칙을 명시한다.

    1. "스킬을 쓰지 않아도 언제나 통과하는 조건은 좋지 않다"
       → 판정 기준은 **판별력(discrimination)** 을 입증해야 한다.
         모든 입력을 통과시키는 기준은 기준이 아니다.
    2. With-skill vs Without-skill A/B 로 **개입의 효과를 수치화**한다.
       → '게이트가 옳다'고 선언하는 대신 '게이트를 끈 것과 비교해 얼마나 다른가'를 센다.

  이 모듈은 그 두 원칙을 우리 증거 게이트에 적용한다. LLM 호출이 없으므로
  API 쿼터와 무관하게 언제든 재현 가능하다.

제공 기능:
  discrimination_report() — 증거 수준별로 features.json 전체를 판정해
      '몇 건을 통과시키는가'를 센다. 수준 간 차이가 곧 A/B 결과다.
  run_log_stats()        — harness_runtime.log 에서 시도 횟수·소요 시간·결과 분포를 추출.
      하네스가 실제로 어떻게 돌았는지에 대한 사후 측정.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness import verify
from harness.verify import LEVELS, verify_feature


# ══════════════════════════════════════════════════════════════════════════════
# 1. 판별력 측정 — 증거 수준별 A/B
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LevelOutcome:
    """한 증거 수준이 features.json 전체에 대해 내린 판정."""

    level: str
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    reject_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)

    @property
    def accept_rate(self) -> float:
        return len(self.accepted) / self.total if self.total else 0.0


def _reason_class(reason: str) -> str:
    """거부 사유를 분류한다 — 어떤 이유로 막혔는지 분포를 보기 위해."""
    if "실패 테스트" in reason:
        return "회귀(스위트 빨간불)"
    if "테스트가 0건" in reason:
        return "테스트 없음"
    if "태그 테스트" in reason and "실패" in reason:
        return "태그 테스트 실패"
    if "검증하는 테스트가 없습니다" in reason:
        return "기능 태그 없음"
    if "명세 단계" in reason:
        return "단계 미검증"
    if "jest" in reason.lower():
        return "실행 불가"
    return "기타"


def discrimination_report(
    project_root: str,
    features: list[dict[str, Any]] | None = None,
    levels: tuple[str, ...] = LEVELS,
) -> dict[str, Any]:
    """증거 수준별로 전체 기능을 판정해 판별력을 센다.

    핵심 해석:
      `suite` 수준(= TS-006 동작)이 통과시키는 건수가 `feature` 수준보다 훨씬 많다면,
      그 차이가 바로 "스위트 녹색"이 기능 증거로서 **무의미했던 정도**다.
      모든 기능을 통과시키는 수준은 판별력 0 — 기준으로 쓸 수 없다.

    jest 는 **한 번만** 실행하고 모든 수준이 그 결과를 공유한다.
    """
    if features is None:
        path = Path(project_root) / "features.json"
        features = json.loads(path.read_text(encoding="utf-8"))

    results, diag = verify.run_jest_json(project_root)
    if results is None:
        return {"error": diag, "levels": {}}

    outcomes: dict[str, LevelOutcome] = {}
    for level in levels:
        outcome = LevelOutcome(level=level)
        for feature in features:
            v = verify_feature(project_root, feature, level=level, results=results)
            fid = str(feature.get("id", "?"))
            if v.ok:
                outcome.accepted.append(fid)
            else:
                outcome.rejected.append(fid)
                cls = _reason_class(v.reason)
                outcome.reject_reasons[cls] = outcome.reject_reasons.get(cls, 0) + 1
        outcomes[level] = outcome

    # 현재 features.json 의 플래그와 판정의 불일치 — 감사 대상
    flagged = {str(f.get("id")) for f in features if f.get("passes")}
    baseline = outcomes.get("suite")
    strict = outcomes.get("feature")

    report: dict[str, Any] = {
        "total_features": len(features),
        "suite_total": results.get("numTotalTests", 0),
        "suite_failed": results.get("numFailedTests", 0),
        "levels": {
            lvl: {
                "accepted": len(o.accepted),
                "rejected": len(o.rejected),
                "accept_rate": round(o.accept_rate, 4),
                "accepted_ids": o.accepted,
                "reject_reasons": o.reject_reasons,
            }
            for lvl, o in outcomes.items()
        },
        "flagged_passes": sorted(flagged),
    }

    if baseline and strict:
        # A/B 결과: 기준을 바꿨을 때 통과 건수가 얼마나 줄어드는가
        report["ab_suite_vs_feature"] = {
            "baseline_accepted": len(baseline.accepted),
            "treatment_accepted": len(strict.accepted),
            "filtered_out": len(baseline.accepted) - len(strict.accepted),
            "discrimination": round(
                1 - (len(strict.accepted) / len(baseline.accepted)), 4
            ) if baseline.accepted else 0.0,
        }

    if strict:
        accepted = set(strict.accepted)
        # 플래그는 통과인데 판정은 거부 → 증거 없는 통과 (회수 대상)
        report["unsupported_flags"] = sorted(flagged - accepted)
        # 판정은 통과인데 플래그는 미완성 → 과소 평가 (부여 대상)
        report["unclaimed_passes"] = sorted(accepted - flagged)

    return report


def format_discrimination(report: dict[str, Any]) -> str:
    """판별력 보고서를 사람이 읽을 표로 만든다."""
    if "error" in report:
        return f"[오류] {report['error']}"

    lines = [
        "=" * 68,
        "증거 게이트 판별력 측정 (revfactory 방법론: A/B + 판별력 원칙)",
        "=" * 68,
        f"  대상 기능 {report['total_features']}건 | "
        f"테스트 스위트 {report['suite_total']}건 중 실패 {report['suite_failed']}건",
        "",
        "  수준별 통과 건수 — 모든 기능을 통과시키는 수준은 판별력 0",
        "  " + "-" * 64,
        f"  {'수준':<10} {'통과':>6} {'거부':>6} {'통과율':>8}   주요 거부 사유",
    ]
    for lvl, data in report["levels"].items():
        reasons = ", ".join(
            f"{k} {v}" for k, v in sorted(
                data["reject_reasons"].items(), key=lambda kv: -kv[1]
            )[:2]
        ) or "-"
        lines.append(
            f"  {lvl:<10} {data['accepted']:>6} {data['rejected']:>6} "
            f"{data['accept_rate']*100:>7.1f}%   {reasons}"
        )

    ab = report.get("ab_suite_vs_feature")
    if ab:
        lines += [
            "",
            "  A/B — baseline(suite, TS-006 동작) vs treatment(feature, TS-008)",
            "  " + "-" * 64,
            f"  baseline 통과   : {ab['baseline_accepted']}건  "
            "(스위트가 녹색이면 무엇이든 통과)",
            f"  treatment 통과  : {ab['treatment_accepted']}건  "
            "(기능 ID 태그 통과 테스트를 요구)",
            f"  걸러낸 건수     : {ab['filtered_out']}건",
            f"  판별력          : {ab['discrimination']*100:.1f}% "
            "(baseline 통과 중 근거 없이 통과했던 비율)",
        ]

    unsupported = report.get("unsupported_flags") or []
    unclaimed = report.get("unclaimed_passes") or []
    lines += ["", "  플래그 감사", "  " + "-" * 64]
    lines.append(
        f"  증거 없는 통과 (회수 대상): {', '.join(unsupported) if unsupported else '없음'}"
    )
    lines.append(
        f"  증거 있는데 미완성 표시   : {', '.join(unclaimed) if unclaimed else '없음'}"
    )
    lines.append("=" * 68)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 2. 실행 로그 사후 측정
# ══════════════════════════════════════════════════════════════════════════════

_TASK_START_RE = re.compile(r"^TASK START: (.+)$")
_SESSION_RE = re.compile(r"^SESSION: (.+)$")
_TIME_RE = re.compile(r"^TIME: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$")
_EXIT_RE = re.compile(r"^\[ERROR\] Task failed with exit code (-?\d+)")
_SUCCESS_RE = re.compile(r"^\[SUCCESS\] Task completed")
_INFRA_RE = re.compile(r"^\[INFRA\] exit=(-?\d+)")
_TIMEOUT_RE = re.compile(r"^\[⏱ Timeout\]")
#: night_shift 가 finally 에서 항상 남기는 구조화된 종료 줄 (사람용 마커보다 우선한다)
_END_RE = re.compile(
    r"^\[END\] exit=(None|-?\d+) outcome=(\S+)(?: elapsed_sec=([\d.]+))?"
)


@dataclass
class RunRecord:
    task: str = ""
    session: str = ""
    started_at: str = ""
    outcome: str = "unknown"
    exit_code: int | None = None
    duration_sec: float | None = None


def run_log_stats(log_path: str) -> dict[str, Any]:
    """harness_runtime.log 에서 시도별 결과·소요 시간을 추출한다.

    하네스가 **실제로 어떻게 돌았는지**에 대한 유일한 사후 기록이다.
    (revfactory 가이드의 "total_tokens / duration_ms 를 즉시 저장한다" 에 대응하는
     우리 쪽 측정 지점. 토큰 수는 현재 기록되지 않아 추출할 수 없다 — 한계로 남는다.)
    """
    path = Path(log_path)
    if not path.is_file():
        return {"error": f"로그 파일이 없습니다: {log_path}"}

    runs: list[RunRecord] = []
    current: RunRecord | None = None

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()

        m = _TASK_START_RE.match(line)
        if m:
            if current is not None:
                runs.append(current)
            current = RunRecord(task=m.group(1))
            continue
        if current is None:
            continue

        m = _SESSION_RE.match(line)
        if m:
            current.session = m.group(1)
            continue
        m = _TIME_RE.match(line)
        if m:
            current.started_at = m.group(1)
            continue
        m = _EXIT_RE.match(line)
        if m:
            current.exit_code = int(m.group(1))
            current.outcome = "failed"
            continue
        if _SUCCESS_RE.match(line):
            current.exit_code = 0
            current.outcome = "success"
            continue
        m = _INFRA_RE.match(line)
        if m:
            current.exit_code = int(m.group(1))
            current.outcome = "infra"
            continue
        if _TIMEOUT_RE.match(line):
            current.exit_code = -1
            current.outcome = "timeout"
            continue
        # [END] 는 finally 에서 항상 기록되므로 사람용 마커보다 신뢰도가 높다 — 마지막에 덮어쓴다
        m = _END_RE.match(line)
        if m:
            code, outcome, elapsed = m.groups()
            current.exit_code = None if code == "None" else int(code)
            current.outcome = outcome
            if elapsed is not None:
                current.duration_sec = float(elapsed)

    if current is not None:
        runs.append(current)

    # [END] 가 없는 과거 블록만 연속 시작 시각의 차이로 소요 시간을 추정한다.
    # (추정치이므로 다음 런의 시작까지 포함된다 — [END] elapsed_sec 가 있으면 그쪽이 정확하다)
    for i, run in enumerate(runs[:-1]):
        if run.duration_sec is not None:
            continue
        try:
            t0 = datetime.strptime(run.started_at, "%Y-%m-%d %H:%M:%S")
            t1 = datetime.strptime(runs[i + 1].started_at, "%Y-%m-%d %H:%M:%S")
            run.duration_sec = (t1 - t0).total_seconds()
        except ValueError:
            continue

    outcomes: dict[str, int] = {}
    per_session: dict[str, int] = {}
    durations: list[float] = []
    for run in runs:
        outcomes[run.outcome] = outcomes.get(run.outcome, 0) + 1
        if run.session:
            per_session[run.session] = per_session.get(run.session, 0) + 1
        if run.duration_sec is not None:
            durations.append(run.duration_sec)

    return {
        "total_runs": len(runs),
        "outcomes": outcomes,
        "attempts_per_session": per_session,
        "max_attempts": max(per_session.values()) if per_session else 0,
        "median_duration_sec": (
            sorted(durations)[len(durations) // 2] if durations else None
        ),
        "fastest_sec": min(durations) if durations else None,
        "runs": runs,
    }


def format_run_log(stats: dict[str, Any]) -> str:
    """실행 로그 통계를 사람이 읽을 표로."""
    if "error" in stats:
        return f"[오류] {stats['error']}"

    lines = [
        "=" * 68,
        "실행 로그 사후 측정 (harness_runtime.log)",
        "=" * 68,
        f"  총 시도 {stats['total_runs']}회 | "
        f"세션당 최대 {stats['max_attempts']}회",
        "",
        "  결과 분포",
        "  " + "-" * 64,
    ]
    for outcome, count in sorted(stats["outcomes"].items(), key=lambda kv: -kv[1]):
        share = count / stats["total_runs"] * 100 if stats["total_runs"] else 0
        lines.append(f"  {outcome:<12} {count:>4}회  ({share:4.1f}%)")

    med = stats.get("median_duration_sec")
    fast = stats.get("fastest_sec")
    lines += ["", "  소요 시간 (연속 시작 시각 차이로 추정)", "  " + "-" * 64]
    lines.append(f"  중앙값: {med if med is not None else '측정 불가'}초")
    lines.append(f"  최단  : {fast if fast is not None else '측정 불가'}초")
    if fast is not None and fast < 15:
        lines.append(
            "  ⚠ 10초 안팎의 시도가 존재한다 — 기능 구현이 아니라 즉시 실패한 런이다"
        )
    lines.append("=" * 68)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 3. 게이트 판정 집계 (TS-015)
# ══════════════════════════════════════════════════════════════════════════════
#
# 토큰 없는 모드에서 측정해야 할 것은 비용이 아니라 **게이트가 무엇을 걸렀는가** 다.
# `harness.cli` 가 판정마다 남기는 [GATE] 줄을 집계한다.
#
# 핵심 지표:
#   거부 사유 분포   — 세션이 주로 무엇을 빠뜨리는가
#   통과까지 거부 수 — 기능 하나를 입증하는 데 몇 번 막혔는가
#   revoke 횟수      — **게이트가 틀렸던 횟수** (통과시킨 뒤 회수한 사건)

_GATE_RE = re.compile(
    r"^\[GATE\] feature=(\S+) command=(\S+) verdict=(\S+) level=(\S+) reason=(.*)$"
)


def gate_stats(log_path: str) -> dict[str, Any]:
    """실행 기록에서 게이트 판정을 집계한다."""
    path = Path(log_path)
    if not path.is_file():
        return {"error": f"로그 파일이 없습니다: {log_path}"}

    verdicts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    per_feature: dict[str, dict[str, int]] = {}

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _GATE_RE.match(raw.strip())
        if not m:
            continue
        fid, command, verdict, _level, reason = m.groups()
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if verdict == "reject":
            reasons[reason.strip()] = reasons.get(reason.strip(), 0) + 1
        slot = per_feature.setdefault(fid, {"accept": 0, "reject": 0, "revoke": 0})
        if verdict in slot:
            slot[verdict] += 1

    total = sum(verdicts.values())
    return {
        "total_judgements": total,
        "verdicts": verdicts,
        "reject_reasons": reasons,
        "per_feature": per_feature,
        # 게이트가 통과시킨 뒤 회수된 사건 — 게이트의 오판 횟수
        "revocations": verdicts.get("revoke", 0),
        "reject_rate": round(verdicts.get("reject", 0) / total, 4) if total else None,
    }


def format_gate_stats(stats: dict[str, Any]) -> str:
    """게이트 집계를 사람이 읽을 표로."""
    if "error" in stats:
        return f"[오류] {stats['error']}"
    if not stats["total_judgements"]:
        return (
            "=" * 68 + "\n"
            "게이트 판정 집계\n" + "=" * 68 + "\n"
            "  기록된 판정이 없습니다 — `cli verify` / `cli mark` 를 쓰면 쌓입니다.\n"
            + "=" * 68
        )

    bar = "=" * 68
    lines = [bar, "게이트 판정 집계 — 게이트가 무엇을 걸렀는가", bar]
    lines.append(f"  총 판정 {stats['total_judgements']}건")
    lines.append("")
    lines.append("  판정 분포")
    lines.append("  " + "-" * 64)
    labels = {"accept": "통과", "reject": "거부", "revoke": "회수(unmark)"}
    for verdict, count in sorted(stats["verdicts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {labels.get(verdict, verdict):<14} {count:>4}건")
    if stats["reject_rate"] is not None:
        lines.append(f"  거부율         {stats['reject_rate'] * 100:>5.1f}%")

    if stats["reject_reasons"]:
        lines += ["", "  거부 사유 — 세션이 주로 무엇을 빠뜨리는가", "  " + "-" * 64]
        for reason, count in sorted(stats["reject_reasons"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {reason:<20} {count:>4}건")

    noisy = {f: s for f, s in stats["per_feature"].items() if s["reject"] or s["revoke"]}
    if noisy:
        lines += ["", "  기능별 (거부 또는 회수가 있던 것만)", "  " + "-" * 64]
        for fid, s in sorted(noisy.items()):
            lines.append(
                f"  {fid:<8} 통과 {s['accept']} / 거부 {s['reject']} / 회수 {s['revoke']}"
            )

    if stats["revocations"]:
        lines += [
            "",
            f"  ⚠ 회수 {stats['revocations']}건 — 게이트가 통과시킨 뒤 번복한 사건이다.",
            "    게이트가 보지 못한 결함이 있었다는 뜻이므로 사유를 추적할 가치가 있다.",
        ]
    lines.append(bar)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="하네스 자체를 측정한다 (LLM 호출 없음)"
    )
    parser.add_argument("--project", default="./web_target", help="대상 프로젝트 루트")
    parser.add_argument("--log", default="./harness_runtime.log", help="실행 로그 경로")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = parser.parse_args()

    report = discrimination_report(args.project)
    stats = run_log_stats(args.log)
    gates = gate_stats(args.log)

    if args.json:
        stats.pop("runs", None)
        print(json.dumps({"discrimination": report, "run_log": stats, "gate": gates},
                         ensure_ascii=False, indent=2))
    else:
        print(format_discrimination(report))
        print()
        print(format_gate_stats(gates))
        print()
        print(format_run_log(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

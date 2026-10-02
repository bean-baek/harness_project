"""
harness/cli.py
──────────────
토큰을 쓰지 않는 하네스 — 추론은 Claude Code 세션이 하고, **강제는 이 CLI가 한다.**

배경 (TS-010):
  하네스 코드를 성격별로 세어보면 이렇다.
    결정론적 기계(게이트·측정·도구·라우팅)   2,060줄  — 토큰 0
    유료 LLM API를 돌리기 위한 코드          2,357줄  — 토큰 전량
  **가치 있는 쪽은 이미 무료였다.** 유료 API는 '추론 엔진' 역할만 했고, 그 역할은
  이미 구독으로 비용을 낸 Claude Code 세션이 대신할 수 있다.

왜 마크다운만으로는 안 되는가:
  revfactory/harness 처럼 전부 마크다운으로 가면 **강제력이 사라진다.**
  TS-006 의 교훈이 정확히 그것이다 — "테스트를 먼저 실행하십시오"가 docstring 안의
  권고였을 때 에이전트는 무시하고 자가 채점했다. 마크다운은 권고만 할 수 있다.
  그래서 절차는 마크다운(.claude/skills/harness/SKILL.md)에 두고,
  판정은 이 CLI(파이썬)에 둔다. 세션이 아무리 "구현했다"고 주장해도
  `harness mark` 가 거부하면 플래그는 바뀌지 않는다.

의존성:
  langchain / langgraph / API 키가 **필요 없다**. 표준 라이브러리 + jest 만 쓴다.

사용법:
  python -m harness.cli next                  다음 미구현 기능과 태그 규약 출력
  python -m harness.cli show F-004            특정 기능 명세 출력
  python -m harness.cli verify F-004          게이트 판정만 (플래그 변경 없음)
  python -m harness.cli mark F-004            게이트 통과 시에만 통과로 기록
  python -m harness.cli unmark F-004          미완성으로 되돌림 (증거 제거)
  python -m harness.cli mutate F-005          증거가 실제로 무는지 측정 (느림)
  python -m harness.cli tags                  증거 태그가 옳은 기능을 가리키는지 검사
  python -m harness.cli report                판별력 + 실행 로그 측정
  python -m harness.cli audit                 현재 통과 플래그 전수 재검증
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.verify import (  # noqa: E402
    apply_flag,
    find_index,
    load_features,
    verify_feature,
)

DEFAULT_PROJECT = "./web_target"
DEFAULT_LOG = os.environ.get("HARNESS_RUN_LOG", "./harness_runtime.log")


# ── 실행 기록 (TS-015) ───────────────────────────────────────────────────────
# 유료 모드에서는 night_shift 가 [END] 줄을 남겨 사후 측정이 가능했다. 토큰 없는 모드로
# 옮기면서 그 기록자가 사라져 metrics.run_log_stats 가 **고아가 됐다** — 측정 계층의
# 절반이 이제 쓰지 않는 모드만 측정하고 있었다.
#
# 그래서 CLI 가 그 역할을 이어받는다. 측정 대상은 토큰이 아니라 **게이트가 무엇을
# 걸렀는가** 다: 거부 횟수, 사유 분포, 통과까지 걸린 거부 수, unmark(게이트가 틀렸던 횟수).

#: 거부 사유를 분류한다 — metrics 의 _reason_class 와 같은 어휘를 쓴다
_REASON_PATTERNS = (
    ("회귀", "실패 테스트"),
    ("테스트 없음", "테스트가 0건"),
    ("태그 테스트 실패", "태그 테스트"),
    ("기능 태그 없음", "검증하는 테스트가 없습니다"),
    ("단계 미검증", "명세 단계"),
    ("실행 불가", "jest"),
)


def classify_reason(reason: str) -> str:
    """거부 사유 한 줄을 분류명으로 환원한다."""
    for label, needle in _REASON_PATTERNS:
        if needle in reason:
            return label
    return "기타" if reason else "-"


def record_run(
    log_path: str | None,
    *,
    feature_id: str,
    description: str,
    command: str,
    verdict: str,
    reason: str = "",
    level: str = "",
    exit_code: int = 0,
    elapsed: float = 0.0,
) -> None:
    """게이트 판정 한 건을 로그에 남긴다.

    블록 형식은 TS-009 의 night_shift 기록과 **동일**하게 유지한다 —
    metrics.run_log_stats 가 두 시대의 기록을 같은 파서로 읽을 수 있어야 한다.
    `[GATE]` 줄은 게이트 전용 차원(판정·사유·수준)을 추가한다.
    """
    if not log_path:
        return
    bar = "=" * 60
    safe_reason = re.sub(r"\s+", " ", reason).strip()[:160]
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{bar}\n")
            f.write(f"TASK START: {description}\n")
            f.write(f"SESSION: cli-{command}/{feature_id}\n")
            f.write(f"TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{bar}\n")
            f.write(
                f"[GATE] feature={feature_id} command={command} verdict={verdict}"
                f" level={level or '-'} reason={classify_reason(safe_reason)}\n"
            )
            if safe_reason:
                f.write(f"[GATE-DETAIL] {safe_reason}\n")
            f.write(f"[END] exit={exit_code} outcome={verdict} elapsed_sec={round(elapsed, 1)}\n")
    except OSError:
        pass          # 기록 실패가 판정을 가려선 안 된다 (TS-009 의 원칙)


# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────

def _bar(char: str = "─", width: int = 68) -> str:
    return char * width


def _print_feature(feature: dict, show_steps: bool = True) -> None:
    fid = feature.get("id", "?")
    print(f"  {fid}  [{feature.get('category', '-')}]  {feature.get('description', '')}")
    if show_steps and feature.get("steps"):
        print("  명세 단계:")
        for i, step in enumerate(feature["steps"], 1):
            print(f"    {i}. {step}")


def _print_tag_contract(feature: dict) -> None:
    fid = feature.get("id", "F-XXX")
    desc = str(feature.get("description", ""))[:34]
    steps = feature.get("steps") or []
    print()
    print("  테스트 태그 규약 — 이걸 지키지 않으면 mark 가 거부한다")
    print(f"  {_bar()}")
    print(f'    describe("{fid}: {desc}", ...)')
    if steps:
        print(f'    test("{fid}.1: {str(steps[0])[:40]}", ...)')
        print(f"    ... 단계 {len(steps)}개까지 (단계 태그는 선택, 커버리지로 기록된다)")


# ── 명령 ─────────────────────────────────────────────────────────────────────

def cmd_next(args) -> int:
    features = load_features(args.project)
    pending = [f for f in features if not f.get("passes")]
    if not pending:
        print("모든 기능이 통과 상태입니다.")
        return 0

    done = len(features) - len(pending)
    print(_bar("="))
    print(f"다음 작업  ({done}/{len(features)} 완료)")
    print(_bar("="))
    _print_feature(pending[0])
    _print_tag_contract(pending[0])
    print()
    print("  구현 후: python -m harness.cli mark " + str(pending[0].get("id")))
    print(_bar("="))
    return 0


def cmd_show(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    feature = features[idx]
    print(_bar("="))
    print(f"기능 명세  (passes={feature.get('passes', False)})")
    print(_bar("="))
    _print_feature(feature)
    v = feature.get("verification")
    if v:
        print()
        print("  기록된 증거:")
        print(f"    {v.get('summary', '-')}")
        for name in v.get("evidence_tests", []):
            print(f"      · {name}")
        if v.get("steps_uncovered"):
            print(f"    미검증 단계: {v['steps_uncovered']}")
    _print_tag_contract(feature)
    print(_bar("="))
    return 0


def cmd_verify(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2

    started = time.monotonic()
    result = verify_feature(args.project, features[idx], level=args.level)
    verdict = "통과" if result.ok else "거부"
    print(f"[{verdict}] {args.feature_id} (수준: {result.level})")
    print(f"  현황: {result.summary()}")
    if not result.ok:
        print(f"  사유: {result.reason}")
    if result.tagged_passed:
        print("  근거 테스트:")
        for name in result.tagged_passed:
            print(f"    · {name}")

    record_run(
        getattr(args, "log", None),
        feature_id=args.feature_id,
        description=str(features[idx].get("description", "")),
        command="verify",
        verdict="accept" if result.ok else "reject",
        reason=result.reason,
        level=result.level,
        exit_code=0 if result.ok else 1,
        elapsed=time.monotonic() - started,
    )
    return 0 if result.ok else 1


def cmd_mark(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    started = time.monotonic()
    applied, message = apply_flag(args.project, idx, passes=True)
    print(message)
    record_run(
        getattr(args, "log", None),
        feature_id=args.feature_id,
        description=str(features[idx].get("description", "")),
        command="mark",
        verdict="accept" if applied else "reject",
        reason="" if applied else message,
        level=os.environ.get("HARNESS_EVIDENCE_LEVEL", "feature"),
        exit_code=0 if applied else 1,
        elapsed=time.monotonic() - started,
    )
    return 0 if applied else 1


def cmd_unmark(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    started = time.monotonic()
    applied, message = apply_flag(args.project, idx, passes=False)
    print(message)
    # unmark 은 **게이트가 틀렸던 횟수**를 세는 지표다 — 통과시킨 뒤 회수한 사건.
    record_run(
        getattr(args, "log", None),
        feature_id=args.feature_id,
        description=str(features[idx].get("description", "")),
        command="unmark",
        verdict="revoke",
        exit_code=0 if applied else 1,
        elapsed=time.monotonic() - started,
    )
    return 0 if applied else 1


def cmd_audit(args) -> int:
    """현재 통과로 기록된 기능들이 지금 기준으로도 자격이 있는지 전수 재검증."""
    from harness.verify import audit_features

    features = load_features(args.project)
    claimed = [f for f in features if f.get("passes")]
    if not claimed:
        print("통과로 기록된 기능이 없습니다.")
        return 0

    print(_bar("="))
    print(f"통과 플래그 전수 재검증  ({len(claimed)}건, 수준: {args.level or 'feature'})")
    print(_bar("="))
    bad = 0
    for feature, v in audit_features(args.project, claimed, level=args.level):
        mark = "통과" if v.ok else "거부"
        print(f"  [{mark}] {feature.get('id')}  {v.summary()}")
        if not v.ok:
            bad += 1
            print(f"         사유: {v.reason[:110]}")
    print(_bar("="))
    if bad:
        print(f"  ⚠ {bad}건이 현재 기준을 만족하지 않습니다 — unmark 또는 테스트 보강이 필요합니다.")
    return 1 if bad else 0


def cmd_mutate(args) -> int:
    """증거가 실제로 무는지 돌연변이로 측정한다 (느리다 — 게이트가 아니다)."""
    from harness.mutate import format_mutation, mutate_feature

    features = load_features(args.project)
    if find_index(features, args.feature_id) < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    report = mutate_feature(args.project, args.feature_id, max_files=args.max_files)
    print(format_mutation(report))
    if "error" in report:
        return 2
    # 생존한 변이가 있으면 1 — 증거에 구멍이 있다는 신호다 (차단은 하지 않는다)
    return 1 if report["survived"] else 0


def cmd_init(args) -> int:
    """프로젝트를 검수해 `.harness.json` 을 만든다.

    종료 코드: 0 생성 완료 / 1 이미 존재 / 2 검수 실패.
    `--dry-run` 은 쓰지 않고 결과만 보여준다 — 추론이 틀렸을 때 사용자가 먼저
    확인할 수 있어야 한다. 자동 감지를 조용히 신뢰하지 않는다는 것이 이 프로젝트의
    기본 입장이다 (TS-009: 측정이 무엇을 근거로 했는지 보이지 않으면 믿을 수 없다).
    """
    from harness import project

    root = Path(args.harness_root).resolve()
    try:
        cfg, findings = project.load(root)
    except ValueError as exc:
        print(f"[오류] {exc}")
        return 2

    print(project.format_findings(cfg, findings, root))

    if args.dry_run:
        print("\n  --dry-run — 아무것도 쓰지 않았습니다.")
        return 0
    try:
        path = project.save(cfg, root)
    except FileExistsError as exc:
        print(f"\n[건너뜀] {exc}")
        return 1
    print(f"\n  작성: {path}")
    print("  틀린 값이 있으면 그 키만 고치십시오 — 선언된 키가 추론을 이깁니다.")
    return 0


def cmd_inspect(args) -> int:
    """객관 지표와 의도가 필요한 후보를 나눠 보고한다.

    종료 코드: 0 위반 없음 / 1 자동 판정에서 위반 발견 / 2 검수 실패.
    위반을 종료 코드로 알리는 이유: 이 검사들은 **의도와 무관하게** 틀린 것이므로
    CI 에서 차단해도 근거가 선다. 의도가 필요한 후보는 종료 코드에 영향을 주지 않는다.
    """
    from harness import inspect as inspect_mod

    root = Path(args.harness_root).resolve()
    try:
        report = inspect_mod.inspect_project(root)
    except ValueError as exc:
        print(f"[오류] {exc}")
        return 2

    print(inspect_mod.format_report(report, root))

    if args.write_draft and report.draft:
        draft_path = root / "features.draft.json"
        if draft_path.exists() and not args.force:
            print(f"\n[건너뜀] {draft_path} 가 이미 있습니다 (--force 로 덮어쓰기).")
        else:
            draft_path.write_text(
                json.dumps(report.draft, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"\n  초안 작성: {draft_path} ({len(report.draft)}건)")
            print("  이것은 **명세가 아닙니다.** 읽고 판단한 뒤 features.json 으로 옮기십시오 —")
            print("  검수가 뽑은 항목을 그대로 명세로 쓰면 코드를 그 코드로 검사하는 순환입니다.")

    return 1 if any(c.auto and c.verdict == "violated" for c in report.checks) else 0


def cmd_tags(args) -> int:
    """증거 태그가 옳은 기능을 가리키는지 검사한다 (보고만, 차단 없음)."""
    from harness.tags import format_tag_report, lint_tags, scan_tags

    features = load_features(args.project)
    print(format_tag_report(args.project, features))
    issues = lint_tags(args.project, features, refs=scan_tags(args.project))
    # unknown-id 는 명백한 오류이므로 종료 코드로 알린다. 나머지는 보고만 한다.
    return 1 if any(i.kind == "unknown-id" for i in issues) else 0


def cmd_report(args) -> int:
    from harness.metrics import (
        discrimination_report,
        format_discrimination,
        format_gate_stats,
        format_run_log,
        gate_stats,
        run_log_stats,
    )

    report = discrimination_report(args.project)
    if args.json:
        stats = run_log_stats(args.log)
        stats.pop("runs", None)
        print(json.dumps(
            {"discrimination": report, "run_log": stats, "gate": gate_stats(args.log)},
            ensure_ascii=False, indent=2))
        return 0
    print(format_discrimination(report))
    print()
    print(format_gate_stats(gate_stats(args.log)))
    print()
    print(format_run_log(run_log_stats(args.log)))
    return 0


# ── 진입점 ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m harness.cli",
        description="토큰을 쓰지 않는 하네스 — 추론은 세션이, 강제는 이 CLI가 한다",
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="대상 프로젝트 루트")

    # 공통 옵션 부모 — 서브명령 뒤에 --project 를 써도 받는다
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=DEFAULT_PROJECT, help="대상 프로젝트 루트")

    # 판정을 내리는 명령은 실행 기록을 남긴다 (TS-015)
    judging = argparse.ArgumentParser(add_help=False)
    judging.add_argument("--log", default=DEFAULT_LOG, help="실행 기록 파일")
    judging.add_argument("--no-log", dest="log", action="store_const", const=None,
                         help="실행 기록을 남기지 않는다")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("next", parents=[common], help="다음 미구현 기능과 태그 규약")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("show", parents=[common], help="특정 기능 명세와 기록된 증거")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", parents=[common, judging], help="게이트 판정만 (플래그 변경 없음)")
    p.add_argument("feature_id")
    p.add_argument("--level", choices=("suite", "feature", "step"), default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("mark", parents=[common, judging], help="게이트 통과 시에만 통과로 기록")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("unmark", parents=[common, judging], help="미완성으로 되돌림 (증거 제거)")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_unmark)

    p = sub.add_parser("audit", parents=[common], help="통과 플래그 전수 재검증")
    p.add_argument("--level", choices=("suite", "feature", "step"), default=None)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("mutate", parents=[common],
                       help="증거가 실제로 무는지 돌연변이로 측정 (느림, 게이트 아님)")
    p.add_argument("feature_id")
    p.add_argument("--max-files", type=int, default=2, dest="max_files",
                   help="변이 대상 파일 수 (기본 2)")
    p.set_defaults(func=cmd_mutate)

    p = sub.add_parser("init", help="프로젝트를 검수해 .harness.json 생성")
    p.add_argument("--harness-root", default=".", dest="harness_root",
                   help="하네스 루트 (기본: 현재 디렉터리)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="쓰지 않고 검수 결과만 출력")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("inspect", help="객관 지표 추출 + 의도가 필요한 항목 분리 보고")
    p.add_argument("--harness-root", default=".", dest="harness_root")
    p.add_argument("--write-draft", action="store_true", dest="write_draft",
                   help="features.draft.json 에 명세 초안을 쓴다 (명세 아님 — 검토 필요)")
    p.add_argument("--force", action="store_true", help="기존 초안을 덮어쓴다")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("tags", parents=[common], help="증거 태그가 옳은 기능을 가리키는지 검사")
    p.set_defaults(func=cmd_tags)

    p = sub.add_parser("report", parents=[common], help="판별력 + 실행 로그 측정")
    p.add_argument("--log", default="./harness_runtime.log")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"[오류] 파일을 찾을 수 없습니다: {exc}")
        return 2
    except json.JSONDecodeError as exc:
        print(f"[오류] features.json 파싱 실패: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

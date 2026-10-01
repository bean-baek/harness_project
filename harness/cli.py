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
  python -m harness.cli report                판별력 + 실행 로그 측정
  python -m harness.cli audit                 현재 통과 플래그 전수 재검증
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.verify import (  # noqa: E402
    apply_flag,
    find_index,
    load_features,
    verify_feature,
)

DEFAULT_PROJECT = "./web_target"


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
    return 0 if result.ok else 1


def cmd_mark(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    applied, message = apply_flag(args.project, idx, passes=True)
    print(message)
    return 0 if applied else 1


def cmd_unmark(args) -> int:
    features = load_features(args.project)
    idx = find_index(features, args.feature_id)
    if idx < 0:
        print(f"[오류] 기능 ID '{args.feature_id}' 를 찾을 수 없습니다.")
        return 2
    applied, message = apply_flag(args.project, idx, passes=False)
    print(message)
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


def cmd_report(args) -> int:
    from harness.metrics import (
        discrimination_report,
        format_discrimination,
        format_run_log,
        run_log_stats,
    )

    report = discrimination_report(args.project)
    if args.json:
        stats = run_log_stats(args.log)
        stats.pop("runs", None)
        print(json.dumps({"discrimination": report, "run_log": stats},
                         ensure_ascii=False, indent=2))
        return 0
    print(format_discrimination(report))
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

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("next", parents=[common], help="다음 미구현 기능과 태그 규약")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("show", parents=[common], help="특정 기능 명세와 기록된 증거")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", parents=[common], help="게이트 판정만 (플래그 변경 없음)")
    p.add_argument("feature_id")
    p.add_argument("--level", choices=("suite", "feature", "step"), default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("mark", parents=[common], help="게이트 통과 시에만 통과로 기록")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("unmark", parents=[common], help="미완성으로 되돌림 (증거 제거)")
    p.add_argument("feature_id")
    p.set_defaults(func=cmd_unmark)

    p = sub.add_parser("audit", parents=[common], help="통과 플래그 전수 재검증")
    p.add_argument("--level", choices=("suite", "feature", "step"), default=None)
    p.set_defaults(func=cmd_audit)

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

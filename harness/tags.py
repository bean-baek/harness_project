"""
harness/tags.py
───────────────
증거 규약 자체를 검사한다 — 태그가 **옳은 기능을 가리키는지**.

배경 (TS-014):
  TS-008 이후 "기능 ID 를 인용하는 통과 테스트"가 증거다. 그런데 **태그가 틀릴 수 있다.**
  실측: `web_target/tests/smoke.spec.ts` 의 라벨 3건이 명세와 전혀 달랐다.

    F-017  스펙 라벨 "성능 기준"        vs  명세 "경쟁 종료 시 승자에게 디지털 배지와 보상을 부여한다"
    F-018  스펙 라벨 "키보드 접근성"    vs  명세 "대시보드에 주간 완료 통계 차트가 표시된다"
    F-020  스펙 라벨 "네트워크 오류"    vs  명세 "읽지 않은 알림 수를 벨 아이콘에 뱃지로 표시한다"

  게이트는 ID 문자열만 맞으면 통과시키므로 이 오기를 전혀 보지 못한다.
  E2E 가 증거로 계수되는 순간 **엉뚱한 기능에 크레딧이 간다.**

설계 원칙:
  이 모듈은 **게이트가 아니라 보고기**다. 라벨 유사도는 휴리스틱이므로 자동 차단하지 않고
  두 문자열과 수치를 함께 출력해 사람이 판단하게 한다. 임계값으로 통과/탈락을 가르면
  "근거 없는 상수"를 또 하나 만드는 셈이다 (TS-008 의 EVAL_WEIGHTS 교훈).

  또한 어떤 기능이 **E2E 태그만 가지고 있는지** 보고한다 — 게이트는 jest 만 실행하므로
  그런 기능은 "증거 있음"으로 보이지만 게이트 기준으로는 증거가 0이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: 규약 판정은 ProjectConfig 와 같은 구현을 쓴다 — 호출자가 넷이고
#: 그중 셋이 `endswith` 로 따로 구현해 pytest 에서 전부 틀렸다 (TS-025).
from harness.project import matches_pattern

#: 테스트 파일 판별 기본값 — `.harness.json` 이 없을 때만 쓴다.
#: 이 값은 설정 외부화 이전의 하드코딩과 **같다** (동작 변화 없음).
UNIT_SUFFIXES = (".test.ts", ".test.tsx")
E2E_SUFFIXES = (".spec.ts", ".spec.tsx")

def id_regex(id_pattern: str) -> re.Pattern[str]:
    """프로젝트 ID 형식에서 태그 포착 정규식을 만든다.

    `id_pattern` 은 캡처 그룹이 없어야 한다 — 여기서 그룹 1(ID)과
    그룹 2(단계 번호)를 쓰기 때문이다. 괄호가 들어오면 비캡처로 바꾼다.
    """
    safe = re.sub(r"\((?!\?)", "(?:", id_pattern)
    return re.compile(r"(?<![\w-])(" + safe + r")(?:[.#-](\d+))?")


#: 스위트 판별 — 생태계마다 '이 블록이 이 기능을 검증한다'고 주장하는 구문이 다르다.
#: 라벨 불일치 판정은 **스위트 라벨에만** 적용한다 (개별 테스트는 단계를 서술한다).
_SUITE_RE_BY_RUNNER: dict[str, re.Pattern[str]] = {}

#: 라벨은 **ID 를 포함한 문자열 리터럴 전체**에서 얻는다.
#: 콜론만 믿었다가 `test('… 표시 (F-020)')` 처럼 ID 가 뒤에 오는 형태를 놓쳤다.
#: 리터럴을 쓰면 `F-004: 설명` 과 `설명 (F-020)` 둘 다 처리된다.
_LITERAL_RE = re.compile(r"""(['"`])((?:(?!\1).){3,160})\1""")


#: 라벨 꼬리 정리
_TRAIL_RE = re.compile(r"[\s,;:.·\-]+$")

#: 이보다 짧은(정제 후) 라벨은 판정하지 않는다 — 노이즈를 불일치로 몰지 않는다
MIN_LABEL_CHARS = 4


@dataclass
class TagRef:
    """테스트 파일에서 발견한 기능 ID 참조 한 건."""

    feature_id: str
    label: str
    file: str
    line: int
    kind: str          # 'unit' | 'e2e'
    is_suite: bool = False   # describe(...) 블록의 라벨인가
    step: int | None = None  # 단계 태그(F-004.2)의 단계 번호


def _kind_of(path: Path, units: tuple[str, ...], e2es: tuple[str, ...]) -> str | None:
    """단위 / E2E / 테스트 아님. E2E 를 먼저 보는 이유: `.spec.ts` 가 양쪽 규약에
    모두 쓰이는 프로젝트에서 E2E 선언이 있으면 그쪽이 더 구체적인 선언이다."""
    name = path.name
    if matches_pattern(name, e2es):
        return "e2e"
    if matches_pattern(name, units):
        return "unit"
    return None


def _suite_regex(runner: str) -> re.Pattern[str]:
    """`이 블록이 기능을 검증한다`고 주장하는 구문 — 런너별.

    pytest 규약: 기능 ID 는 **클래스 docstring 또는 테스트 함수의 docstring**
    문자열 리터럴에 넣는다. 함수 이름(`def test_f005_...`)에는 하이픈을 쓸 수 없어
    `F-005` 형태가 들어가지 않으므로, 이름이 아니라 문자열을 본다.
    """
    cached = _SUITE_RE_BY_RUNNER.get(runner)
    if cached is not None:
        return cached
    if runner == "pytest":
        pattern = re.compile(r"(?:^|[\s])class\s+\w+")
    else:
        pattern = re.compile(r"(?:^|[\s.;=(])(?:test\.)?describe(?:\.\w+)?\s*\(")
    _SUITE_RE_BY_RUNNER[runner] = pattern
    return pattern


def scan_tags(project_root: str, cfg: Any | None = None) -> list[TagRef]:
    """프로젝트의 모든 테스트 파일에서 기능 ID 참조를 수집한다.

    규약(접미사·ID 형식·스위트 구문)은 `.harness.json` 이 정한다. 설정이 없으면
    이 모듈의 기본 상수가 쓰이고, 그것은 설정 외부화 이전과 같은 값이다.
    """
    if cfg is None:
        from harness.project import config_for
        cfg = config_for(project_root)
    units = tuple(cfg.unit_suffixes) or UNIT_SUFFIXES
    e2es = tuple(cfg.e2e_suffixes) or E2E_SUFFIXES
    id_re = id_regex(cfg.id_pattern)
    suite_re = _suite_regex(cfg.runner)

    root = Path(project_root).resolve()
    refs: list[TagRef] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        kind = _kind_of(path, units, e2es)
        if kind is None:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        for lineno, line in enumerate(lines, 1):
            # 태그는 **문자열 리터럴**(테스트 이름) 안에만 있다.
            # 줄 전체를 스캔했더니 주석에 적은 ID("ARIA 는 F-026 이 다룬다")까지
            # 태그로 집계되었다. 주석은 증거가 아니다.
            is_suite = bool(suite_re.search(line))
            for lit in _LITERAL_RE.finditer(line):
                text = lit.group(2)
                matches = list(id_re.finditer(text))
                if not matches:
                    continue
                label = _TRAIL_RE.sub("", id_re.sub("", text).strip(" ()[]{}:·-"))
                for match in matches:
                    refs.append(TagRef(
                        feature_id=match.group(1),
                        label=label,
                        file=rel,
                        line=lineno,
                        kind=kind,
                        is_suite=is_suite,
                        step=int(match.group(2)) if match.group(2) else None,
                    ))
    return refs


def _has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))


def same_script(a: str, b: str) -> bool:
    """두 문자열이 같은 문자 체계인지 — 다르면 2-gram 겹침으로 판정할 수 없다."""
    return _has_hangul(a) == _has_hangul(b)


# ── 라벨 유사도 ──────────────────────────────────────────────────────────────

def _bigrams(text: str) -> set[str]:
    """공백·구두점을 제거한 뒤 문자 2-gram 집합. 한국어에 어절 분리보다 견고하다."""
    cleaned = re.sub(r"[\s\W_]+", "", text)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def label_overlap(label: str, description: str) -> float:
    """라벨의 2-gram 중 명세에도 있는 비율 (0.0~1.0).

    라벨이 명세의 축약이라는 전제이므로 **라벨 기준 포함율**을 쓴다
    (Jaccard 는 길이 차이에 지나치게 민감하다).
    """
    a, b = _bigrams(label), _bigrams(description)
    if not a:
        return 1.0          # 라벨이 비어 있으면 판정 보류 (불일치로 몰지 않는다)
    return len(a & b) / len(a)


@dataclass
class TagIssue:
    kind: str            # 'unknown-id' | 'label-mismatch' | 'e2e-only'
    feature_id: str
    detail: str
    where: str = ""
    overlap: float | None = None


def lint_tags(
    project_root: str,
    features: list[dict[str, Any]],
    refs: Iterable[TagRef] | None = None,
    suspicious_below: float = 0.50,
) -> list[TagIssue]:
    """태그가 가리키는 기능이 실제 명세와 맞는지 검사한다.

    세 가지를 보고한다.
      unknown-id      features.json 에 없는 ID 를 인용
      label-mismatch  라벨이 명세와 거의 겹치지 않음 (사람 확인 필요)
      e2e-only        E2E 에만 태그가 있어 게이트 기준으로는 증거 0
    """
    if refs is None:
        refs = scan_tags(project_root)
    refs = list(refs)

    by_id = {str(f.get("id")): f for f in features}
    issues: list[TagIssue] = []

    # 1) 존재하지 않는 ID
    for ref in refs:
        if ref.feature_id not in by_id:
            issues.append(TagIssue(
                kind="unknown-id",
                feature_id=ref.feature_id,
                detail=f"features.json 에 없는 ID — 라벨 {ref.label!r}",
                where=f"{ref.file}:{ref.line}",
            ))

    # 2) 라벨 불일치 — **참조마다** 평가한다.
    #    기능별 최댓값만 보면 잘 붙은 라벨 하나가 틀린 라벨들을 가린다 (실측으로 확인).
    #    언어가 다르면 2-gram 겹침으로 판정할 수 없으므로 따로 분류한다.
    seen_positions: set[tuple[str, str, int]] = set()
    candidates: dict[str, list[tuple[float, TagRef]]] = {}
    unverifiable: dict[str, TagRef] = {}
    for ref in refs:
        feature = by_id.get(ref.feature_id)
        if feature is None:
            continue
        # describe 라벨만 평가한다 — 개별 케이스 이름은 단계 서술이므로 대상이 아니다.
        # 단계 태그가 붙은 참조도 제외한다 (기능 설명이 아니라 단계를 가리킨다).
        if not ref.is_suite or ref.step is not None:
            continue
        if len(re.sub(r"[\s\W_]+", "", ref.label)) < MIN_LABEL_CHARS:
            continue
        key = (ref.feature_id, ref.file, ref.line)
        if key in seen_positions:
            continue
        seen_positions.add(key)

        desc = str(feature.get("description", ""))
        if not same_script(ref.label, desc):
            unverifiable.setdefault(ref.feature_id, ref)
            continue
        candidates.setdefault(ref.feature_id, []).append(
            (label_overlap(ref.label, desc), ref)
        )

    # 판정은 **기능 단위**로 한다: 그 기능을 올바로 지칭하는 describe 가 하나라도 있으면
    # 나머지 describe 는 하위 측면을 가리키는 정상적인 이름이다.
    # (참조마다 판정했더니 하위 측면 describe 가 모두 오탐으로 잡혔다)
    for fid, scored in sorted(candidates.items()):
        best = max(s for s, _ in scored)
        if best >= suspicious_below:
            continue
        desc = str(by_id[fid].get("description", ""))
        for score, ref in sorted(scored, key=lambda sr: sr[0]):
            issues.append(TagIssue(
                kind="label-mismatch",
                feature_id=fid,
                detail=f"라벨 {ref.label[:40]!r} ↔ 명세 {desc[:42]!r}",
                where=f"{ref.file}:{ref.line}",
                overlap=round(score, 3),
            ))

    for fid, ref in sorted(unverifiable.items()):
        if fid in candidates:      # 같은 기능에 판정 가능한 라벨이 있으면 보고하지 않는다
            continue
        issues.append(TagIssue(
            kind="label-unverifiable",
            feature_id=fid,
            detail=f"라벨과 명세의 언어가 다르다 — 라벨 {ref.label[:40]!r}",
            where=f"{ref.file}:{ref.line}",
        ))

    # 3) E2E 에만 존재하는 태그 — 게이트(jest)는 보지 못한다
    unit_ids = {r.feature_id for r in refs if r.kind == "unit"}
    e2e_ids = {r.feature_id for r in refs if r.kind == "e2e"}
    for fid in sorted(e2e_ids - unit_ids):
        if fid not in by_id:
            continue
        issues.append(TagIssue(
            kind="e2e-only",
            feature_id=fid,
            detail="E2E 에만 태그가 있다 — 게이트는 jest 만 실행하므로 증거로 계수되지 않는다",
        ))

    return issues


def format_tag_report(
    project_root: str,
    features: list[dict[str, Any]],
) -> str:
    """사람이 읽는 태그 검사 보고서."""
    refs = scan_tags(project_root)
    issues = lint_tags(project_root, features, refs=refs)

    unit = sum(1 for r in refs if r.kind == "unit")
    e2e = sum(1 for r in refs if r.kind == "e2e")
    files = len({r.file for r in refs})

    bar = "=" * 68
    lines = [
        bar,
        "증거 태그 검사 — 태그가 옳은 기능을 가리키는가",
        bar,
        f"  태그 참조 {len(refs)}건 (단위 {unit} / E2E {e2e}) · 파일 {files}개",
        "",
    ]
    if not issues:
        lines += ["  문제 없음", bar]
        return "\n".join(lines)

    groups: dict[str, list[TagIssue]] = {}
    for issue in issues:
        groups.setdefault(issue.kind, []).append(issue)

    titles = {
        "unknown-id": "존재하지 않는 기능 ID 를 인용",
        "label-mismatch": "라벨이 명세와 거의 겹치지 않음 (사람 확인 필요)",
        "label-unverifiable": "라벨과 명세의 언어가 달라 기계 판정 불가 (사람 확인)",
        "e2e-only": "E2E 에만 태그가 있어 게이트 증거로 계수되지 않음",
    }
    for kind in ("unknown-id", "label-mismatch", "label-unverifiable", "e2e-only"):
        found = groups.get(kind)
        if not found:
            continue
        lines.append(f"  [{kind}] {titles[kind]} — {len(found)}건")
        lines.append("  " + "-" * 64)
        for issue in found:
            suffix = f"  (겹침 {issue.overlap:.0%})" if issue.overlap is not None else ""
            lines.append(f"    {issue.feature_id}  {issue.detail}{suffix}")
            if issue.where:
                lines.append(f"              {issue.where}")
        lines.append("")

    lines.append("  주의: 라벨 유사도는 휴리스틱이다. 차단하지 않고 보고만 한다 —")
    lines.append("        임계값으로 통과/탈락을 가르면 근거 없는 상수가 하나 더 생긴다.")
    lines.append(bar)
    return "\n".join(lines)

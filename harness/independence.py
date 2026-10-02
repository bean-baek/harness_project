"""
harness/independence.py
───────────────────────
**증거의 독립성 — 테스트가 검증 대상의 구조를 자기가 공급하는가.**

배경 (TS-013):
  증거 사다리는 두 칸에서 멈춰 있었다.

    이름 (TS-008) → 소스 실행 (TS-016) → [빈칸]

  빈칸이 돌연변이라고 생각했지만 아니다. 돌연변이는 **같은 채널의 깊이**를 재고,
  TS-013 이 드러낸 것은 **채널의 독립성**이었다.

  F-005 는 게이트를 통과했고 jest 51/51 이 녹색이었다. 그런데 실 브라우저에서
  전혀 동작하지 않았다 — 앱에 `/dashboard` 라우트가 아예 없었다. 왜 못 잡았나:

    ProtectedRoute.test.tsx  <Route path="/dashboard" element={<ProtectedRoute>…} />
                             ← 테스트가 라우트를 **직접 만들어** 감쌌다

  테스트가 검증 대상의 구조를 공급하면 그 구조는 검증되지 않는다. 앱이 그 경로를
  선언했는지는 묻지 않은 채 "보호가 동작한다"만 확인한 것이다.

  TS-013 의 수정은 `routes.ts` 단일 출처로 **그 기능 하나만** 고쳤다.
  **정책은 바뀌지 않았다** — 다음 기능이 같은 실수를 반복하는 것을 막는 장치가 없다.
  이 모듈이 그 정책이다.

판정은 임계값이 아니라 사실이다:
  앱이 컬렉션을 선언했을 때(`export const PROTECTED_PATHS = [...]`), 그 기능의
  태그 테스트가
    (a) 그 컬렉션을 **import 해서 순회**하는가          → 앱의 선언을 읽는다
    (b) 컬렉션의 멤버를 **문자열로 직접 적는가**        → 자급 (hand-rolled)
  둘 다 `import 했는가 / 멤버 리터럴이 있는가` 라는 사실 질문이다. 점수가 없다.

  실측으로 확인한 대비:
    ProtectedRoute.test.tsx  PROTECTED_PATHS 미import + '/dashboard' 리터럴 → 자급
    AppRoutes.test.tsx       PROTECTED_PATHS import 후 .map / test.each      → 독립

왜 게이트가 아니라 보고인가:
  "자급"이 곧 결함은 아니다. 단위 테스트가 픽스처를 만드는 것은 정상이며,
  문제는 그것이 **유일한 증거**일 때다. 통과/탈락으로 가르려면 "채널 몇 개면
  충분한가"를 정해야 하고 그것은 근거 없는 상수가 된다 (`EVAL_WEIGHTS` 의 실수).
  그래서 `tags.py` 와 같은 자리에 둔다 — 사실을 세어 보고하고, 수치를 본 뒤
  게이트로 올릴지는 운영자가 정한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.project import ProjectConfig, config_for

#: 앱이 "단일 출처"로 선언한 컬렉션 — 대문자 이름 + 문자열 2개 이상.
#: 대문자와 2개 이상을 요구하는 이유: 소문자 지역 배열이나 한 개짜리는 '선언'이라기보다
#: 구현 세부사항이고, 그것까지 세면 보고가 노이즈로 덮인다.
_COLLECTION_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Z][A-Z0-9_]*)\s*(?::[^=]+?)?=\s*\[([^\]]*)\]"
)
_STRING_LITERAL_RE = re.compile(r"""['"]([^'"\n]{1,120})['"]""")

#: 소스로 볼 확장자
_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".py")


@dataclass
class Collection:
    """앱이 선언한 단일 출처 컬렉션."""

    name: str
    members: list[str]
    declared_in: str

    def __hash__(self) -> int:
        return hash((self.name, self.declared_in))


@dataclass
class SelfSupplied:
    """태그 테스트가 앱의 선언을 손으로 복사한 사건 한 건.

    `severity` 로 두 갈래를 나눈다 — 실측에서 섞였고, 섞으면 신호가 죽는다
    (TS-017 의 교훈: 오해를 부르는 보고는 없는 보고보다 나쁘다).

      `enumerated`  멤버 **2개 이상**을 import 없이 적었다 → 컬렉션을 손으로 재현했다.
                    TS-013 의 모양이다. `ProtectedRoute.test.tsx` 가 `/` 와
                    `/dashboard` 로 라우트 테이블을 직접 만든 것이 여기 속한다.
      `hard-coded`  멤버 **1개**만 적었다 → 기대값 단정이다.
                    `expect(mockNavigate).toHaveBeenCalledWith('/profile')` 처럼
                    구조를 공급하는 것이 아니다. 다만 앱이 그 경로를 바꾸면 테스트는
                    그대로 통과하면서 앱이 깨지므로 **약한 결합**으로 기록한다.

    경계를 2로 두는 근거: '집합을 열거한다'와 '원소 하나를 지목한다'를 가르는
    최솟값이다. 점수가 아니라 개수이며, 어느 쪽이든 원본 리터럴을 함께 출력해
    사람이 직접 확인할 수 있게 한다.
    """

    collection: str
    declared_in: str
    test_file: str
    literals: list[str]

    @property
    def severity(self) -> str:
        return "enumerated" if len(self.literals) >= 2 else "hard-coded"

    def line(self) -> str:
        shown = ", ".join(self.literals[:4])
        if len(self.literals) > 4:
            shown += f" … 외 {len(self.literals) - 4}개"
        if self.severity == "enumerated":
            what = f"멤버 {len(self.literals)}개를 열거했다 (컬렉션을 손으로 재현)"
        else:
            what = "멤버 1개를 적었다 (기대값 단정 — 약한 결합)"
        return (f"[{self.severity}] {self.test_file} 가 {self.collection}"
                f"({self.declared_in}) 를 import 하지 않고 {what}: {shown}")


@dataclass
class FeatureIndependence:
    """기능 하나의 증거 독립성."""

    feature_id: str
    unit_files: list[str] = field(default_factory=list)
    e2e_files: list[str] = field(default_factory=list)
    self_supplied: list[SelfSupplied] = field(default_factory=list)

    @property
    def channels(self) -> int:
        return (1 if self.unit_files else 0) + (1 if self.e2e_files else 0)

    @property
    def enumerated(self) -> list[SelfSupplied]:
        """컬렉션을 손으로 재현한 건만 — 등급을 끌어내리는 것은 이것뿐이다."""
        return [s for s in self.self_supplied if s.severity == "enumerated"]

    @property
    def hard_coded(self) -> list[SelfSupplied]:
        return [s for s in self.self_supplied if s.severity == "hard-coded"]

    @property
    def grade(self) -> str:
        """`self-supplied` | `single-channel` | `cross-checked` | `no-evidence`.

        등급은 두 사실의 조합이다. 하나로 합치지 않는 이유: '앱의 선언을 읽는다'와
        '두 채널이 교차 검증한다'는 **다른 것**이다. F-018 은 선언 문제가 없지만
        채널이 하나뿐이고, F-005 는 채널이 둘이지만 자급 테스트가 섞여 있다.
        """
        if not self.unit_files and not self.e2e_files:
            return "no-evidence"
        if self.enumerated and self.channels < 2:
            return "self-supplied"          # TS-013 의 모양
        if self.channels < 2:
            return "single-channel"
        return "cross-checked"

    def reason(self) -> str:
        if self.grade == "no-evidence":
            return "태그된 테스트가 없다"
        if self.grade == "self-supplied":
            return ("태그 테스트가 앱의 선언을 손으로 복사했고 교차 검증 채널이 없다 "
                    "— TS-013 이 터진 모양이다")
        if self.grade == "single-channel":
            return (f"채널이 하나뿐이다 (단위 {len(self.unit_files)} / E2E 0) "
                    "— 그 채널이 놓치는 것을 아무도 보지 않는다")
        base = f"채널 2개 (단위 {len(self.unit_files)} / E2E {len(self.e2e_files)})"
        if self.enumerated:
            return (base + f" — 컬렉션을 손으로 재현한 테스트 {len(self.enumerated)}건이"
                    " 있으나 E2E 가 교차 확인한다")
        if self.hard_coded:
            return base + f" — 약한 결합 {len(self.hard_coded)}건 (기대값 단정)"
        return base + " — 자급 없음"


# ── 앱의 선언 수집 ───────────────────────────────────────────────────────────

def declared_collections(project_root: str | Path,
                         cfg: ProjectConfig | None = None) -> list[Collection]:
    """앱이 단일 출처로 선언한 컬렉션 목록. 테스트 파일은 보지 않는다."""
    root = Path(project_root).resolve()
    if cfg is None:
        cfg = config_for(root)
    test_suffixes = cfg.all_test_suffixes()

    out: list[Collection] = []
    seen: set[tuple[str, str]] = set()
    for d in cfg.source_dirs:
        base = (root / d).resolve()
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in _SOURCE_EXTS:
                continue
            if p.name.endswith(test_suffixes) or "node_modules" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            for m in _COLLECTION_RE.finditer(text):
                name, body = m.group(1), m.group(2)
                members = _STRING_LITERAL_RE.findall(body)
                if len(members) < 2:
                    continue
                key = (name, rel)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Collection(name, members, rel))
    return out


# ── 자급 판정 ────────────────────────────────────────────────────────────────

def _imports(text: str, name: str) -> bool:
    """그 이름을 import 했는가 (named / namespace 양쪽)."""
    if re.search(rf"import\s*\{{[^}}]*\b{re.escape(name)}\b[^}}]*\}}", text):
        return True
    # `import * as routes` 후 `routes.PROTECTED_PATHS`
    return bool(re.search(rf"\b\w+\.{re.escape(name)}\b", text))


def self_supplied_in(test_file: Path, root: Path,
                     collections: list[Collection]) -> list[SelfSupplied]:
    """이 테스트 파일이 앱의 선언을 손으로 복사했는가."""
    try:
        text = test_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = str(test_file.relative_to(root)).replace("\\", "/")
    literals = set(_STRING_LITERAL_RE.findall(text))

    out: list[SelfSupplied] = []
    for coll in collections:
        if _imports(text, coll.name):
            continue                     # 앱의 선언을 읽는다 — 자급이 아니다
        hits = sorted(l for l in literals if l in coll.members)
        if hits:
            out.append(SelfSupplied(coll.name, coll.declared_in, rel, hits))
    return out


# ── 기능별 분석 ──────────────────────────────────────────────────────────────

def analyze(project_root: str | Path, feature_id: str,
            cfg: ProjectConfig | None = None,
            collections: list[Collection] | None = None,
            refs: list[Any] | None = None) -> FeatureIndependence:
    """기능 하나의 증거 독립성. 런너를 실행하지 않는다 — 전부 정적 분석이다."""
    from harness.tags import scan_tags

    root = Path(project_root).resolve()
    if cfg is None:
        cfg = config_for(root)
    if collections is None:
        collections = declared_collections(root, cfg)
    if refs is None:
        refs = scan_tags(str(root), cfg)

    result = FeatureIndependence(feature_id=feature_id)
    unit, e2e = set(), set()
    for ref in refs:
        if ref.feature_id != feature_id:
            continue
        (unit if ref.kind == "unit" else e2e).add(ref.file)
    result.unit_files = sorted(unit)
    result.e2e_files = sorted(e2e)

    for rel in result.unit_files:
        result.self_supplied += self_supplied_in(root / rel, root, collections)
    return result


def audit_independence(project_root: str | Path,
                       features: list[dict[str, Any]]) -> list[FeatureIndependence]:
    """통과로 표시된 기능 전체의 독립성. 한 번의 스캔으로 전부 처리한다."""
    from harness.tags import scan_tags

    root = Path(project_root).resolve()
    cfg = config_for(root)
    collections = declared_collections(root, cfg)
    refs = scan_tags(str(root), cfg)

    out: list[FeatureIndependence] = []
    for f in features:
        fid = str(f.get("id", "")).strip()
        if not fid or not f.get("passes"):
            continue
        out.append(analyze(root, fid, cfg, collections, refs))
    return out


# ── 보고 ─────────────────────────────────────────────────────────────────────

_GRADE_LABEL = {
    "cross-checked":  "교차검증",
    "single-channel": "단일채널",
    "self-supplied":  "자급",
    "no-evidence":    "증거없음",
}


def format_independence(results: list[FeatureIndependence],
                        collections: list[Collection]) -> str:
    bar = "=" * 72
    lines = [bar, "증거 독립성 — 테스트가 검증 대상의 구조를 자기가 공급하는가 (TS-013)", bar, ""]

    lines.append(f"  앱이 선언한 단일 출처 컬렉션 {len(collections)}개")
    for c in collections:
        lines.append(f"    {c.name}  ({c.declared_in})  멤버 {len(c.members)}개")
    if not collections:
        lines.append("    없음 — 자급 판정의 기준이 되는 선언이 없다 (채널 수만 본다)")
    lines.append("")

    counts: dict[str, int] = {}
    for r in results:
        counts[r.grade] = counts.get(r.grade, 0) + 1
    summary = " · ".join(
        f"{_GRADE_LABEL[g]} {counts.get(g, 0)}"
        for g in ("cross-checked", "single-channel", "self-supplied", "no-evidence")
    )
    n_enum = sum(len(r.enumerated) for r in results)
    n_hard = sum(len(r.hard_coded) for r in results)
    lines += [
        f"  통과 기능 {len(results)}개 — {summary}",
        f"  자급 사건: 컬렉션 재현(enumerated) {n_enum}건 · 약한 결합(hard-coded) {n_hard}건",
        "  " + "-" * 68, "",
    ]

    order = {"self-supplied": 0, "no-evidence": 1, "single-channel": 2, "cross-checked": 3}
    for r in sorted(results, key=lambda x: (order.get(x.grade, 9), x.feature_id)):
        lines.append(f"  [{_GRADE_LABEL[r.grade]}] {r.feature_id}")
        lines.append(f"         채널: 단위 {len(r.unit_files)} / E2E {len(r.e2e_files)}")
        lines.append(f"         {r.reason()}")
        for ss in r.self_supplied:
            lines.append(f"         └ {ss.line()}")
        lines.append("")

    lines += [
        "  " + "-" * 68,
        "  해석:",
        "    자급 자체는 결함이 아니다 — 단위 테스트가 픽스처를 만드는 것은 정상이다.",
        "    문제는 그것이 **유일한 증거**일 때다. F-005 는 jest 51/51 녹색에",
        "    게이트 통과였지만 실 브라우저에서 동작하지 않았고, E2E 가 잡았다 (TS-013).",
        "",
        "    통과/탈락으로 가르지 않는 이유: '채널 몇 개면 충분한가'를 정하면",
        "    근거 없는 상수가 하나 더 생긴다. 수치를 먼저 쌓고 판단한다.",
        bar,
    ]
    return "\n".join(lines)

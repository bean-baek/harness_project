"""
harness/tools.py
────────────────
도구 권한 계층 정의 및 등록

논문 근거 (Section 4.2.1):
  READ_ONLY    → 승인 없이 실행 가능
  STATEFUL     → 감사 로그 필수, 확인 체크포인트 권장
  IRREVERSIBLE → 반드시 인간 승인 후 실행
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool

import config
from harness.verify import apply_flag, run_jest, verify_feature


# ── 도구 권한 계층 상수 ──────────────────────────────────────────────────────

ToolTier = Literal["READ_ONLY", "STATEFUL", "IRREVERSIBLE"]

TOOL_REGISTRY: dict[str, ToolTier] = {
    "web_search":       "READ_ONLY",
    "read_file":        "READ_ONLY",
    "list_directory":   "READ_ONLY",
    "read_features":    "READ_ONLY",
    "read_progress":    "READ_ONLY",
    "write_file":       "STATEFUL",
    "run_tests":        "STATEFUL",
    "bash_command":     "STATEFUL",
    "git_commit":       "STATEFUL",
    "update_features":  "STATEFUL",
    "write_progress":   "STATEFUL",
    "deploy_staging":   "STATEFUL",
    "log_trouble":      "STATEFUL",
    "list_troubles":    "READ_ONLY",
    "read_trouble":     "READ_ONLY",
    "deploy_prod":      "IRREVERSIBLE",
    "delete_resource":  "IRREVERSIBLE",
}


def get_tool_tier(tool_name: str) -> ToolTier:
    """도구 이름으로 권한 계층을 반환한다."""
    return TOOL_REGISTRY.get(tool_name, "STATEFUL")


def is_irreversible(tool_name: str) -> bool:
    return get_tool_tier(tool_name) == "IRREVERSIBLE"


# ══════════════════════════════════════════════════════════════════════════════
# READ_ONLY 도구 (P-10, P-11)
# ══════════════════════════════════════════════════════════════════════════════

@tool
def read_file(path: str) -> str:
    """
    [READ_ONLY] 지정된 절대 경로의 파일 내용을 읽습니다.

    사용 시점: 소스 코드 분석, 설정 파일 조회.
    금지: 이진 파일, .env 파일(비밀키 포함).
    절대 경로만 허용됩니다.
    """
    abs_path = Path(path).resolve()
    if not abs_path.is_file():
        return f"[오류] 파일을 찾을 수 없습니다: {abs_path}"
    if abs_path.suffix in {".env", ".pem", ".key"}:
        return "[보안 오류] 비밀키/환경변수 파일 읽기는 금지됩니다."
    try:
        return abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[오류] 이진 파일은 읽을 수 없습니다: {abs_path}"


@tool
def list_directory(path: str) -> str:
    """
    [READ_ONLY] 디렉토리 내 파일 목록을 반환합니다.

    사용 시점: 프로젝트 구조 파악, 파일 존재 확인.
    """
    abs_path = Path(path).resolve()
    if not abs_path.is_dir():
        return f"[오류] 디렉토리를 찾을 수 없습니다: {abs_path}"
    entries = sorted(abs_path.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries:
        prefix = "📄" if entry.is_file() else "📁"
        lines.append(f"{prefix} {entry.name}")
    return "\n".join(lines)


@tool
def read_features(project_root: str) -> str:
    """
    [READ_ONLY] features.json을 읽어 아직 통과하지 못한 기능 목록을 반환합니다.

    Returns:
        JSON 문자열 — 다음 구현 대상 기능 목록
    """
    features_path = Path(project_root) / "features.json"
    if not features_path.exists():
        return '[오류] features.json이 없습니다. Initializer를 먼저 실행하십시오.'
    features = json.loads(features_path.read_text(encoding="utf-8"))
    pending = [f for f in features if not f.get("passes", False)]
    return json.dumps(pending, ensure_ascii=False, indent=2)


@tool
def read_progress(project_root: str) -> str:
    """
    [READ_ONLY] gemini-progress.txt를 읽어 이전 세션 진행 상황을 반환합니다.
    """
    progress_path = Path(project_root) / "gemini-progress.txt"
    if not progress_path.exists():
        return "(진행 기록 없음 — 최초 세션입니다)"
    return progress_path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# STATEFUL 도구 (P-12, P-13)
# ══════════════════════════════════════════════════════════════════════════════

@tool
def write_file(path: str, content: str) -> str:
    """
    [STATEFUL] 파일을 생성하거나 덮어씁니다.

    사용 시점: 소스 코드 작성, 설정 파일 업데이트.
    반드시 lint/typecheck 후 git commit과 함께 사용하십시오.
    프로덕션 설정 파일(.env.production) 수정 금지.
    """
    abs_path = Path(path).resolve()
    # 프로덕션 파일 보호
    protected = {".env.production", ".env.prod"}
    if abs_path.name in protected:
        return f"[보안 오류] {abs_path.name} 파일은 직접 수정할 수 없습니다."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return f"[완료] {abs_path} ({len(content)} bytes)"


def _run_jest(
    project_root: str,
    test_path: str = ".",
    coverage: bool = False,
) -> tuple[int | None, str]:
    """harness.verify.run_jest 위임 — jest 실행 로직은 verify 모듈이 소유한다 (TS-008)."""
    return run_jest(project_root, test_path, coverage)


@tool
def run_tests(
    project_root: str,
    test_path: str = ".",
    coverage: bool = False,
) -> str:
    """
    [STATEFUL] Jest 테스트 스위트를 실행합니다.

    사용 시점: 코드 변경 후 회귀 테스트.
    경고: 기존 통과 테스트가 실패하면 즉시 코드 변경을 롤백하십시오.
    실행 전 개발 서버가 실행 중인지 확인하십시오.
    """
    returncode, output = _run_jest(project_root, test_path, coverage)
    if returncode is None:
        return output
    status = "✅ PASS" if returncode == 0 else "❌ FAIL"
    return f"[테스트 결과: {status}]\n{output}"


@tool
def bash_command(
    command: str,
    cwd: str | None = None,
    timeout: int | None = None,
) -> str:
    """
    [STATEFUL] 셸 명령어를 실행합니다.

    사용 시점: git 조작, 서버 시작, 빌드 실행, 패키지 설치.
    금지: rm -rf /, sudo, 프로덕션 서버 직접 수정.
    항상 프로젝트 루트에서 실행하십시오.
    """
    # 위험 명령어 차단
    dangerous = ["rm -rf /", "sudo rm", "DROP TABLE", "format c:"]
    for d in dangerous:
        if d.lower() in command.lower():
            return f"[보안 오류] 위험한 명령어가 감지되었습니다: {d}"
    effective_timeout = timeout if timeout is not None else config.TOOL_TIMEOUTS.get("bash_command", 60)
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        rc = result.returncode
        status = "✅" if rc == 0 else f"❌ (exit {rc})"
        return f"[{status}]\n{output}" if output else f"[{status}] (출력 없음)"
    except subprocess.TimeoutExpired:
        return f"[오류] 명령어 타임아웃 ({effective_timeout}초)"


@tool
def git_commit(
    project_root: str,
    message: str,
    files: list[str] | None = None,
) -> str:
    """
    [STATEFUL] 변경 사항을 git에 커밋합니다.

    사용 시점: 기능 구현 완료, 세션 핸드오프 전.
    커밋 메시지 형식: 'feat: {기능명}' 또는 'fix: {버그명}'
    항상 테스트 통과 후에만 커밋한다.
    """
    safe_message = message.replace("\x00", "").strip()[:500] or "chore: empty message"
    try:
        if files:
            subprocess.run(
                ["git", "add", "--", *files],
                cwd=project_root, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        else:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=project_root, check=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        r = subprocess.run(
            ["git", "commit", "-m", safe_message],
            cwd=project_root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        status = "✅" if r.returncode == 0 else f"❌ (exit {r.returncode})"
        output = (r.stdout + r.stderr).strip()
        return f"[{status}]\n{output}" if output else f"[{status}] (출력 없음)"
    except subprocess.TimeoutExpired:
        return "[오류] git commit 타임아웃 (30초)"
    except subprocess.CalledProcessError as e:
        return f"[오류] git add 실패: {(e.stderr or e.stdout or '').strip()}"
    except FileNotFoundError:
        return "[오류] git 실행 파일을 찾을 수 없습니다."


@tool
def update_features(
    project_root: str,
    feature_index: int,
    passes: bool,
) -> str:
    """
    [STATEFUL] features.json에서 특정 기능의 통과 여부를 업데이트합니다.

    passes=True 는 선언이 아니라 입증입니다. 이 도구는 **직접 전체 테스트 스위트를 실행**하고,
    아래 두 조건을 모두 만족할 때만 플래그를 씁니다.

      1. 스위트에 실패 테스트가 0건 (다른 기능을 깨뜨리지 않았다)
      2. **해당 기능 ID 를 이름에 포함한 통과 테스트가 1개 이상**

    스위트가 녹색이어도 기능 ID 태그가 없으면 거부됩니다 — 녹색 스위트는
    '이 기능이 동작한다'의 증거가 아니기 때문입니다.

    태그 규약:
      기능  → `describe("F-004: 사용자가 로그아웃할 수 있다", ...)`
      단계  → `test("F-004.5: 로그아웃 시 auth_token 이 삭제된다", ...)`

    통과 시 어떤 테스트가 근거였는지, 명세의 어느 단계가 검증되지 않았는지가
    features.json 에 함께 기록됩니다. passes=False(미완성 표시)는 증거 없이 허용됩니다.
    기능을 삭제하거나 description을 변경하지 마십시오.
    """
    # 게이트 정책은 harness.verify 가 소유한다 — langchain 도구와 토큰 없는 CLI가
    # 같은 구현을 공유해야 판정이 갈라지지 않는다 (TS-010).
    _applied, message = apply_flag(project_root, feature_index, passes)
    return message


@tool
def write_progress(
    project_root: str,
    content: str,
) -> str:
    """
    [STATEFUL] gemini-progress.txt에 세션 핸드오프 블록을 추가합니다.

    사용 시점: 세션 종료 직전.
    항상 git_commit과 함께 사용하십시오.
    """
    progress_path = Path(project_root) / "gemini-progress.txt"
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write("\n" + content + "\n")
    return f"[완료] gemini-progress.txt 업데이트 ({len(content)} chars)"


# ══════════════════════════════════════════════════════════════════════════════
# 트러블슈팅 로그 도구 — troubleshooting/ 폴더 관리
# ══════════════════════════════════════════════════════════════════════════════

_TS_SLUG_RE      = re.compile(r"[^a-z0-9\-]+")
_TS_FILENAME_RE  = re.compile(r"^TS-(\d{3})-[a-z0-9\-]+\.md$")
_TS_FRONTMATTER  = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _ts_dir() -> Path:
    path = config.TROUBLESHOOTING_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ts_slugify(title: str) -> str:
    s = title.lower().strip().replace(" ", "-")
    s = _TS_SLUG_RE.sub("-", s).strip("-")
    return s[:60] or "untitled"


def _ts_next_id() -> int:
    max_id = 0
    for p in _ts_dir().glob("TS-*.md"):
        m = _TS_FILENAME_RE.match(p.name)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1


def _ts_parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = _TS_FRONTMATTER.match(text)
    if not m:
        return {}
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta


@tool
def log_trouble(
    title: str,
    category: str,
    severity: str,
    component: str,
    body: str,
    tags: list[str] | None = None,
    status: str = "open",
) -> str:
    """
    [STATEFUL] 새 트러블슈팅 엔트리를 troubleshooting/ 에 생성합니다.

    사용 시점: 동일 증상이 재발할 가능성이 있는 버그/장애를 마주쳤을 때.
    기록 금지: 일회성 오타, 재현 불가한 노이즈, 이미 등록된 동일 이슈.

    Args:
        title:     한 줄 요약 (예: "night_shift가 features.json 경로를 못 찾음")
        category:  runtime | build | config | encoding | concurrency | security | data | other
        severity:  low | medium | high | critical
        component: 가장 관련 깊은 파일 경로 (예: "night_shift.py")
        body:      본문 — Symptoms / Root cause / Fix / Verification / Prevention 섹션을
                   포함한 마크다운 (frontmatter는 제외, 도구가 자동 생성)
        tags:      키워드 리스트 (선택)
        status:    open | resolved | wontfix (기본 open)

    Returns:
        생성된 파일 경로
    """
    valid_cat = {"runtime","build","config","encoding","concurrency","security","data","other"}
    valid_sev = {"low","medium","high","critical"}
    valid_sta = {"open","resolved","wontfix"}
    if category not in valid_cat:
        return f"[오류] category는 {valid_cat} 중 하나여야 합니다."
    if severity not in valid_sev:
        return f"[오류] severity는 {valid_sev} 중 하나여야 합니다."
    if status not in valid_sta:
        return f"[오류] status는 {valid_sta} 중 하나여야 합니다."

    next_id  = _ts_next_id()
    slug     = _ts_slugify(title)
    filename = f"TS-{next_id:03d}-{slug}.md"
    path     = _ts_dir() / filename
    tag_str  = "[" + ", ".join(tags or []) + "]"

    frontmatter = (
        f"---\n"
        f"id: TS-{next_id:03d}\n"
        f"title: {title}\n"
        f"date: {date.today().isoformat()}\n"
        f"category: {category}\n"
        f"severity: {severity}\n"
        f"status: {status}\n"
        f"component: {component}\n"
        f"tags: {tag_str}\n"
        f"---\n\n"
    )
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    return f"[완료] {path}"


@tool
def list_troubles(status: str = "all") -> str:
    """
    [READ_ONLY] troubleshooting/ 엔트리 인덱스를 반환합니다. INDEX.md도 함께 갱신합니다.

    Args:
        status: all | open | resolved | wontfix (기본 all)

    Returns:
        id, status, severity, title, component이 포함된 마크다운 표
    """
    rows = []
    for p in sorted(_ts_dir().glob("TS-*.md")):
        meta = _ts_parse_frontmatter(p)
        if not meta:
            continue
        if status != "all" and meta.get("status") != status:
            continue
        rows.append({
            "id":        meta.get("id", p.stem),
            "status":    meta.get("status", "?"),
            "severity":  meta.get("severity", "?"),
            "title":     meta.get("title", ""),
            "component": meta.get("component", ""),
            "file":      p.name,
        })

    header = "| ID | Status | Severity | Title | Component |\n|---|---|---|---|---|\n"
    body = "".join(
        f"| [{r['id']}]({r['file']}) | {r['status']} | {r['severity']} | {r['title']} | `{r['component']}` |\n"
        for r in rows
    ) or "| (no entries) |  |  |  |  |\n"
    table = header + body

    index_path = _ts_dir() / "INDEX.md"
    index_path.write_text(
        f"# Troubleshooting Index\n\n"
        f"_자동 생성 — `list_troubles` 호출 시 갱신됨._\n\n"
        + table,
        encoding="utf-8",
    )
    return f"[{len(rows)} entries, status={status}]\n\n{table}"


@tool
def read_trouble(ts_id: str) -> str:
    """
    [READ_ONLY] 특정 트러블슈팅 엔트리 전문을 반환합니다.

    Args:
        ts_id: "TS-001" 또는 "001" 또는 "1"

    Returns:
        파일 내용 (frontmatter + 본문)
    """
    digits = "".join(ch for ch in ts_id if ch.isdigit())
    if not digits:
        return f"[오류] 잘못된 ts_id 형식: {ts_id}"
    needle = f"TS-{int(digits):03d}-"
    for p in _ts_dir().glob(f"{needle}*.md"):
        return p.read_text(encoding="utf-8")
    return f"[오류] {ts_id} 엔트리를 찾을 수 없습니다."


# ══════════════════════════════════════════════════════════════════════════════
# IRREVERSIBLE 도구 (P-14, P-15) — 인간 승인 필수
# ══════════════════════════════════════════════════════════════════════════════

@tool
def deploy_prod(
    project_root: str,
    target_env: str,
    approval_token: str,
) -> str:
    """
    [IRREVERSIBLE] ⚠️ 프로덕션 환경에 배포합니다.

    이 도구는 인간 승인(approval_token) 없이 절대 호출하지 마십시오.
    호출 전 반드시 P-20 승인 요청을 통해 명시적 확인을 받아야 합니다.
    스테이징 환경 검증 완료 후에만 사용하십시오.
    """
    if not approval_token or approval_token != os.environ.get("DEPLOY_APPROVAL_TOKEN"):
        return "[보안 오류] 유효하지 않은 승인 토큰입니다. 배포가 차단되었습니다."
    return f"[배포 시작] {target_env} 환경에 배포합니다... (실제 구현 필요)"


@tool
def delete_resource(
    resource_type: str,
    resource_id: str,
    backup_confirmed: bool = False,
    approval_token: str = "",
) -> str:
    """
    [IRREVERSIBLE] ⚠️ 리소스를 삭제합니다.

    삭제 전 반드시 백업 여부를 확인(backup_confirmed=True)하고
    인간 승인(approval_token)을 받으십시오.
    복구 불가능한 작업입니다.
    """
    if not backup_confirmed:
        return "[차단] 백업 확인이 필요합니다. backup_confirmed=True로 설정하십시오."
    if not approval_token:
        return "[차단] 인간 승인 토큰이 필요합니다."
    return f"[삭제 예정] {resource_type}:{resource_id} (실제 구현 필요)"


# ══════════════════════════════════════════════════════════════════════════════
# 도구 컬렉션
# ══════════════════════════════════════════════════════════════════════════════

# Coder 에이전트에게 허용되는 도구 (IRREVERSIBLE 제외)
CODER_TOOLS = [
    read_file,
    list_directory,
    read_features,
    read_progress,
    write_file,
    run_tests,
    bash_command,
    git_commit,
    update_features,
    write_progress,
    log_trouble,
    list_troubles,
    read_trouble,
]

# Evaluator 에이전트에게 허용되는 도구 (READ_ONLY + 테스트 실행)
EVALUATOR_TOOLS = [
    read_file,
    list_directory,
    run_tests,
    bash_command,  # Lighthouse, ESLint 실행용
    list_troubles,
    read_trouble,
]

# Initializer 에이전트에게 허용되는 도구
INITIALIZER_TOOLS = [
    write_file,
    bash_command,
    git_commit,
    write_progress,
]

# Orchestrator — READ_ONLY + 트러블슈팅 조회
ORCHESTRATOR_TOOLS = [
    read_file,
    list_directory,
    read_features,
    read_progress,
    list_troubles,
    read_trouble,
]

# Reflector 에이전트 — 실패 분석 후 장기 기억화
REFLECTOR_TOOLS = [
    list_troubles,
    read_trouble,
    log_trouble,
]

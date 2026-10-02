"""
config.py
─────────
하네스 엔지니어링 전역 설정

모든 설정값은 환경변수 우선, 없으면 기본값 사용.
"""

from __future__ import annotations
import os
from pathlib import Path
# python-dotenv 는 선택 의존성이다 — 토큰을 쓰지 않는 경로(증거 게이트/측정/CLI)는
# API 키가 필요 없으므로 langchain·dotenv 없이도 동작해야 한다.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:                     # pragma: no cover
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False

# ── 경로 ─────────────────────────────────────────────────────────────────────
BASE_DIR            = Path(__file__).resolve().parent
WEB_TARGET_DIR      = BASE_DIR / "web_target"
MEMORY_DIR          = BASE_DIR / ".harness_memory"
TROUBLESHOOTING_DIR = BASE_DIR / "troubleshooting"

# ── Google Gemini API ─────────────────────────────────────────────────────────
GOOGLE_API_KEY    = os.environ.get("GOOGLE_API_KEY", "")
LLM_MODEL         = os.environ.get("HARNESS_LLM_MODEL", "gemini-2.5-pro")
LLM_MAX_TOKENS    = int(os.environ.get("HARNESS_LLM_MAX_TOKENS", "4096"))

# ── LLM 백오프 (TS-005) ───────────────────────────────────────────────────────
# 분당 한도/일시 장애에만 적용된다. 지출 캡 초과·인증 실패는 재시도하지 않고 즉시 중단.
LLM_MAX_ATTEMPTS     = int(os.environ.get("HARNESS_LLM_MAX_ATTEMPTS", "4"))
LLM_BACKOFF_BASE_SEC = float(os.environ.get("HARNESS_LLM_BACKOFF_BASE", "5"))
LLM_BACKOFF_MAX_SEC  = float(os.environ.get("HARNESS_LLM_BACKOFF_MAX", "60"))

# ── 하네스 실행 설정 ──────────────────────────────────────────────────────────
MAX_RETRY         = int(os.environ.get("HARNESS_MAX_RETRY", "5"))
MAX_SESSIONS      = int(os.environ.get("HARNESS_MAX_SESSIONS", "50"))
CONTEXT_THRESHOLD = int(os.environ.get("HARNESS_CONTEXT_THRESHOLD", "150_000"))

# ── 평가 기준 (P-04) ──────────────────────────────────────────────────────────
EVAL_PASS_THRESHOLD = int(os.environ.get("HARNESS_EVAL_THRESHOLD", "75"))
EVAL_WEIGHTS = {
    "functionality": 40,   # 기능성
    "code_quality":  30,   # 코드 품질
    "performance":   20,   # 성능
    "security":      10,   # 보안
}

# ── 기능 완료 증거 게이트 (TS-006) ───────────────────────────────────────────
# update_features(passes=True) 는 전체 테스트 스위트를 직접 실행해 통과를 확인한다.
# 운영자만 끌 수 있다 (에이전트에게는 우회 수단이 없다). 디버깅 외에는 켜 둘 것.
REQUIRE_TEST_EVIDENCE = os.environ.get(
    "HARNESS_REQUIRE_TEST_EVIDENCE", "true"
).lower() == "true"

# ── 증거 수준 (TS-008) ───────────────────────────────────────────────────────
#   suite   — 스위트 녹색만 (TS-006 동작, 하위 호환)
#   feature — 스위트 녹색 + 기능 ID 를 인용하는 통과 테스트 1개 이상  (기본)
#   step    — feature + 명세 steps 전부가 단계 태그 테스트로 덮일 때만 통과
# 어느 수준이든 단계 커버리지는 측정해 features.json 에 기록한다.
EVIDENCE_LEVEL = os.environ.get("HARNESS_EVIDENCE_LEVEL", "feature").lower()

# ── 증거 커버리지 요구 (TS-016) ───────────────────────────────────────────────
# 태그 테스트가 비(非)테스트 소스를 한 줄도 실행하지 않으면 공허한 증거다
# (expect(true).toBe(true) 류). 플래그를 쓰는 순간에만 측정한다 — 기능당 한 번.
REQUIRE_EVIDENCE_COVERAGE = os.environ.get(
    "HARNESS_REQUIRE_EVIDENCE_COVERAGE", "true"
).lower() == "true"

# ── 도구 타임아웃 (초) ────────────────────────────────────────────────────────
TOOL_TIMEOUTS = {
    "bash_command": 60,
    "run_tests":    120,
    "deploy":       300,
}

# ── 체크포인터 ────────────────────────────────────────────────────────────────
USE_PERSISTENT_MEMORY = os.environ.get("HARNESS_PERSISTENT", "false").lower() == "true"
DATABASE_URL          = os.environ.get("DATABASE_URL", "")

# ── 개발 서버 ─────────────────────────────────────────────────────────────────
DEV_PORT  = int(os.environ.get("DEV_PORT", "5173"))
API_PORT  = int(os.environ.get("API_PORT", "3001"))
DEV_URL   = f"http://localhost:{DEV_PORT}"
API_URL   = f"http://localhost:{API_PORT}"

# ── 배포 승인 토큰 (IRREVERSIBLE 도구용) ─────────────────────────────────────
DEPLOY_APPROVAL_TOKEN = os.environ.get("DEPLOY_APPROVAL_TOKEN", "")

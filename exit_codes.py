"""
exit_codes.py
─────────────
main.py 프로세스 종료 코드 정의 — night_shift.py 와 공유한다.

설계 의도 (TS-004, TS-005):
  종료 코드로 **"기능(feature) 실패"와 "인프라 실패"를 구분**한다.
  night_shift.py 는 기능 실패에만 attempt 를 소모하고, 인프라 실패는
  attempt 를 소모하지 않고 전체 런을 즉시 중단한다.

  의존성 없음(stdlib only) — night_shift.py 가 langgraph 임포트 없이
  이 모듈만 읽을 수 있어야 한다.
"""

from __future__ import annotations

# ── 기능 단위 결과 ───────────────────────────────────────────────────────────
OK          = 0   # status=done — 기능 구현 + 평가 PASS
ESCALATED   = 1   # status=escalated|cancelled — 인지된 비정상 종료
NO_PROGRESS = 2   # 그 외 (silent-abort 포함 — reasoning/acting 상태로 끝남)

# ── 인프라 장애 ──────────────────────────────────────────────────────────────
LLM_UNAVAILABLE = 3   # LLM 공급자 사용 불가 (쿼터 초과 / 인증 실패 / 백오프 소진)

#: 기능 탓이 아닌 종료 코드 — attempt 를 소모하지 않고 런 전체를 중단해야 한다.
FATAL_INFRA = frozenset({LLM_UNAVAILABLE})

#: 사람이 읽을 수 있는 라벨 (로그 출력용)
LABELS = {
    OK:              "done",
    ESCALATED:       "escalated/cancelled",
    NO_PROGRESS:     "no-progress (silent-abort)",
    LLM_UNAVAILABLE: "llm-unavailable (infra)",
}


def label(code: int) -> str:
    """종료 코드를 사람이 읽을 수 있는 라벨로 변환한다."""
    return LABELS.get(code, f"unknown({code})")

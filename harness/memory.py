"""
harness/memory.py
─────────────────
Reflexion 에피소드 메모리 관리

논문 근거 (Section 3.3 — Reflexion):
  "자연어 반성(verbal reflection)을 에피소드 메모리에 저장하여
   다음 시도에 활용한다."

  메모리 구조:
    session_id → [reflection_1, reflection_2, ...]
  각 반성 항목은 파일 시스템 + 선택적 벡터 DB에 저장된다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


# ── 저장 경로 설정 ────────────────────────────────────────────────────────────

MEMORY_DIR = Path(os.environ.get("HARNESS_MEMORY_DIR", "./.harness_memory"))


def _ensure_memory_dir() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# ── 에피소드 메모리 저장 ─────────────────────────────────────────────────────

def save_episodic_memory(
    session_id: str,
    reflection: str,
    iteration: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Reflexion 반성 결과를 에피소드 메모리에 저장한다.

    저장 형식:
      .harness_memory/{session_id}/reflection_{iteration}.json
    """
    _ensure_memory_dir()
    session_dir = MEMORY_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "iteration":  iteration,
        "timestamp":  datetime.now().isoformat(),
        "reflection": reflection,
        "metadata":   metadata or {},
    }

    path = session_dir / f"reflection_{iteration:03d}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 에피소드 메모리 로드 ─────────────────────────────────────────────────────

def load_episodic_memory(
    session_id: str,
    max_items: int = 5,
) -> list[str]:
    """
    저장된 반성 기록을 최신 순으로 반환한다.

    Args:
        session_id: 세션 식별자
        max_items:  반환할 최대 항목 수 (기본: 5)

    Returns:
        반성 텍스트 목록 (최신 → 과거 순)
    """
    _ensure_memory_dir()
    session_dir = MEMORY_DIR / session_id
    if not session_dir.exists():
        return []

    files = sorted(session_dir.glob("reflection_*.json"), reverse=True)
    reflections = []
    for f in files[:max_items]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reflections.append(data["reflection"])
        except (json.JSONDecodeError, KeyError):
            continue

    return reflections


# ── 전체 세션 히스토리 로드 ──────────────────────────────────────────────────

def load_session_history(session_id: str) -> list[dict[str, Any]]:
    """
    세션의 전체 반성 히스토리를 딕셔너리 목록으로 반환한다.
    """
    session_dir = MEMORY_DIR / session_id
    if not session_dir.exists():
        return []

    history = []
    for f in sorted(session_dir.glob("reflection_*.json")):
        try:
            history.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError):
            continue
    return history


# ── 메모리 초기화 ────────────────────────────────────────────────────────────

def clear_session_memory(session_id: str) -> None:
    """특정 세션의 에피소드 메모리를 삭제한다."""
    import shutil
    session_dir = MEMORY_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)


# ── 컨텍스트 압축 (P-16 연동) ────────────────────────────────────────────────

def compress_context(
    messages: list[Any],
    max_tokens: int = 100_000,
    compression_ratio: float = 0.3,
) -> list[Any]:
    """
    컨텍스트 윈도우가 임계값에 도달했을 때 메시지를 압축한다.

    논문 근거:
      "context rot: 토큰이 증가할수록 정보 회수 정확도가 감소한다."
      - 에이전트 컨텍스트 엔지니어링 가이드 (2025)

    전략: 초기 시스템 메시지와 최근 N개 메시지를 보존하고
    중간 메시지들을 요약으로 대체한다.
    """
    if len(messages) <= 10:
        return messages  # 압축 불필요

    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    # 시스템 메시지 보존
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    recent_msgs = messages[-6:]   # 최근 6개 보존

    # 중간 메시지 요약 생성
    middle_count = len(messages) - len(system_msgs) - 6
    if middle_count > 0:
        summary_msg = HumanMessage(
            content=f"[컨텍스트 압축: 중간 {middle_count}개 메시지 요약 — "
                    f"최근 {len(recent_msgs)}개 메시지부터 계속]"
        )
        return system_msgs + [summary_msg] + recent_msgs

    return messages


# ── 세션 핸드오프 파일 관리 ──────────────────────────────────────────────────

def read_progress_log(project_root: str) -> str:
    """gemini-progress.txt를 읽어 이전 세션 정보를 반환한다."""
    path = Path(project_root) / "gemini-progress.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_progress_log(project_root: str, content: str) -> None:
    """gemini-progress.txt에 새로운 세션 기록을 추가한다."""
    path = Path(project_root) / "gemini-progress.txt"
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + content + "\n")

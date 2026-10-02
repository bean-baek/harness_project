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

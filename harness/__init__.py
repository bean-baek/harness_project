# harness/__init__.py
"""하네스 패키지.

지연 로딩 주의 (TS-010):
  이전에는 여기서 `harness.state` / `harness.graph` 를 즉시 임포트했다.
  그 결과 `import harness.verify` 나 `import harness.cli` 만 해도 langchain·langgraph 가
  끌려와, **토큰을 쓰지 않는 경로(증거 게이트·측정·CLI)가 유료 API 스택에 묶였다.**

  이제 재export 는 PEP 562 `__getattr__` 로 접근 시점에만 해석한다.
  `from harness import build_harness_graph` 는 그대로 동작하고,
  `harness.verify` / `harness.metrics` / `harness.cli` 는 langchain 없이 임포트된다.
"""

from __future__ import annotations

__all__ = ["HarnessState", "create_initial_state", "build_harness_graph"]

_LAZY = {
    "HarnessState":        ("harness.state", "HarnessState"),
    "create_initial_state": ("harness.state", "create_initial_state"),
    "build_harness_graph": ("harness.graph", "build_harness_graph"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'harness' has no attribute {name!r}")
    from importlib import import_module
    return getattr(import_module(target[0]), target[1])


def __dir__() -> list[str]:
    return sorted(__all__)

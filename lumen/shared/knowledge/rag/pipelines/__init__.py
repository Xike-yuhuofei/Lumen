"""Pre-configured RAG pipelines.

Lumen currently ships with a single built-in provider (`llamaindex`).
Additional providers can still be registered dynamically via the factory layer.

Submodule names resolve on demand so the legacy lumen ``services.rag.pipelines``
compatibility facade reaches the canonical modules.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    import importlib

    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError as exc:
        if exc.name == f"{__name__}.{name}":
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        raise

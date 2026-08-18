"""LlamaIndex RAG pipeline implementation package.

Submodule names resolve on demand so the legacy deeptutor
``services.rag.pipelines.llamaindex`` compatibility facade reaches the
canonical modules.
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

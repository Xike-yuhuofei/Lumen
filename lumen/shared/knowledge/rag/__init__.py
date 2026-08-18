"""RAG service exports.

Submodule names resolve on demand so ``from lumen.shared.knowledge.rag import
X`` (and the legacy deeptutor compatibility facade) reach the canonical
modules.
"""

from __future__ import annotations

from typing import Any

from .factory import (
    DEFAULT_PROVIDER,
    get_pipeline,
    list_pipelines,
    normalize_provider_name,
)
from .file_routing import DocumentType, FileClassification, FileTypeRouter
from .service import RAGService

__all__ = [
    "RAGService",
    "FileTypeRouter",
    "FileClassification",
    "DocumentType",
    "get_pipeline",
    "list_pipelines",
    "normalize_provider_name",
    "DEFAULT_PROVIDER",
]


def __getattr__(name: str) -> Any:
    import importlib

    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError as exc:
        if exc.name == f"{__name__}.{name}":
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        raise

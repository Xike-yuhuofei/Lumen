"""Knowledge services — sources, retrieval, parsing, and KB lifecycle.

The KB lifecycle implementation (``manager``, ``manifest``, ``kb_types``,
``naming``, ``add_documents``, ``initializer``, ``progress_tracker``) lives
directly under this package and is exposed lazily below so importing the
package stays free of the RAG/config import chain. Submodule names resolve on
demand so ``from lumen.shared.knowledge import manager`` (and the legacy lumen
compatibility facade) reach the canonical modules.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DocumentAdder", "KnowledgeBaseInitializer", "KnowledgeBaseManager"]

_PUBLIC_EXPORTS = {
    "DocumentAdder": ("add_documents", "DocumentAdder"),
    "KnowledgeBaseInitializer": ("initializer", "KnowledgeBaseInitializer"),
    "KnowledgeBaseManager": ("manager", "KnowledgeBaseManager"),
}


def __getattr__(name: str) -> Any:
    mapping = _PUBLIC_EXPORTS.get(name)
    if mapping is not None:
        import importlib

        module = importlib.import_module(f"{__name__}.{mapping[0]}")
        return getattr(module, mapping[1])
    import importlib

    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError as exc:
        if exc.name == f"{__name__}.{name}":
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        raise

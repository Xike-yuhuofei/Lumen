# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared._util.embedding.adapters.ollama``.

The Embedding service is owned by ``lumen.shared._util.embedding.adapters.ollama`` (canonical). This
module re-exports it for existing importers and tests only.
"""

from __future__ import annotations

import lumen.shared._util.embedding.adapters.ollama as _canon


def __getattr__(name: str):
    return getattr(_canon, name)


__all__ = list(getattr(_canon, "__all__", ()))

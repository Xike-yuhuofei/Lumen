# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared._util.embedding.adapters.cohere``.

The Embedding service is owned by ``lumen.shared._util.embedding.adapters.cohere`` (canonical). This
module re-exports it for existing importers and tests only.
"""

from __future__ import annotations

import lumen.shared._util.embedding.adapters.cohere as _canon


def __getattr__(name: str):
    return getattr(_canon, name)


__all__ = list(getattr(_canon, "__all__", ()))

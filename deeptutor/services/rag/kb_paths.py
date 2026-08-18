# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared.knowledge.rag.kb_paths``."""

from __future__ import annotations

import lumen.shared.knowledge.rag.kb_paths as _canon


def __getattr__(name: str):
    return getattr(_canon, name)


__all__ = list(getattr(_canon, "__all__", ()))

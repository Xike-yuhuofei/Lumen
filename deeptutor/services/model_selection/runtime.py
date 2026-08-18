# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared.config.model_selection_runtime``."""
from __future__ import annotations

import lumen.shared.config.model_selection_runtime as _canon


def __getattr__(name: str):
    return getattr(_canon, name)
__all__ = list(getattr(_canon, "__all__", ()))

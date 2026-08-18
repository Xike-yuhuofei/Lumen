# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared.config``.

The configuration services are owned by ``lumen/shared/config``.  This package
forwards every attribute — eager and lazily-loaded (provider_runtime /
test_runner) — to the canonical module for existing importers and tests.
"""

from __future__ import annotations

import lumen.shared.config as _canon


def __getattr__(name: str):
    return getattr(_canon, name)


__all__ = list(_canon.__all__)

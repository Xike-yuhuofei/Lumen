# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared._util.provider_registry``.

The LLM provider catalog is owned by ``lumen/shared/_util``.  This module
re-exports it for existing importers and tests only.
"""

from __future__ import annotations

from lumen.shared._util.provider_registry import *  # noqa: F401,F403
from lumen.shared._util.provider_registry import __all__  # noqa: F401

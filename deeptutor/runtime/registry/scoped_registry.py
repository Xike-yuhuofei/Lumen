"""Deprecated compatibility facade — see ``lumen.runtime.tools.scoped_registry``.

The per-turn scoped tool registry is owned by ``lumen/runtime/tools``.  This
module re-exports it for existing importers and tests only.
"""
from __future__ import annotations

from lumen.runtime.tools.scoped_registry import *  # noqa: F401,F403
from lumen.runtime.tools.scoped_registry import __all__  # noqa: F401

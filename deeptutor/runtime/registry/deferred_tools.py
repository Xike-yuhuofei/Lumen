"""Deprecated compatibility facade — see ``lumen.runtime.tools.deferred_tools``.

Deferred-tool loading (progressive disclosure) is owned by
``lumen/runtime/tools``.  This module re-exports it for existing importers
and tests only.
"""
from __future__ import annotations

from lumen.runtime.tools.deferred_tools import *  # noqa: F401,F403
from lumen.runtime.tools.deferred_tools import __all__  # noqa: F401

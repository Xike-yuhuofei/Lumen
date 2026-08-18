"""Deprecated compatibility facade — see ``lumen.runtime.tools.builtin``.

Built-in tool implementations and metadata are owned by
``lumen/runtime/tools``.  This module re-exports them for existing importers
and tests only.  Capability-owned (mastery) tools are registered at boot by
mode.learn and are NOT part of this package.
"""
from __future__ import annotations

from lumen.runtime.tools.builtin import *  # noqa: F401,F403
from lumen.runtime.tools.builtin import __all__  # noqa: F401

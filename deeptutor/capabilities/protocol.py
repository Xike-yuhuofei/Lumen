"""Deprecated compatibility facade — see ``lumen.runtime.agent_loop.capability``.

The loop-capability protocol (``LoopCapability`` / ``PromptBlock``) is owned
by ``lumen/runtime/agent_loop``.  This module re-exports it for existing
importers and tests only.
"""
from __future__ import annotations

from lumen.runtime.agent_loop.capability import *  # noqa: F401,F403
from lumen.runtime.agent_loop.capability import __all__  # noqa: F401

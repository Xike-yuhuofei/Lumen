# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.agent_loop.engine.tool_arg_guard``.

The tool-argument guard is owned by ``lumen/runtime/agent_loop``.  This module
re-exports it for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.agent_loop.engine.tool_arg_guard import *  # noqa: F401,F403
from lumen.runtime.agent_loop.engine.tool_arg_guard import __all__  # noqa: F401

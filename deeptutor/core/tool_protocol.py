# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.tool_protocol``.

The tool protocol (``BaseTool`` / ``ToolDefinition`` / ``ToolParameter`` /
``ToolResult`` / ``ToolLookup`` / …) is owned by ``lumen/runtime``.  This
module re-exports it for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.tool_protocol import *  # noqa: F401,F403
from lumen.runtime.tool_protocol import __all__  # noqa: F401

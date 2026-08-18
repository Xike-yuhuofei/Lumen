# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.agent_loop.engine.labels``.

The protocol-label parsing helpers are owned by ``lumen/runtime/agent_loop``.
This module re-exports them for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.agent_loop.engine.labels import *  # noqa: F401,F403
from lumen.runtime.agent_loop.engine.labels import __all__  # noqa: F401

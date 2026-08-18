"""Deprecated compatibility facade — see ``lumen.runtime.stream.event_bus``.

The application event bus is owned by ``lumen/runtime/stream``.  This module
re-exports it for existing importers and tests only.
"""
from __future__ import annotations

from lumen.runtime.stream.event_bus import *  # noqa: F401,F403
from lumen.runtime.stream.event_bus import __all__  # noqa: F401

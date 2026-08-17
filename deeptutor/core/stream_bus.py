"""Deprecated compatibility facade — see ``lumen.runtime.stream.bus``.

The ``StreamBus`` fan-out event bus and its per-turn registry are owned by
``lumen/runtime/stream`` since Phase 6B2.  This module re-exports them for
existing importers and tests only.
"""

from lumen.runtime.stream.bus import *  # noqa: F401,F403

__all__ = ["StreamBus", "register_bus", "unregister_bus", "get_bus"]  # noqa: F405

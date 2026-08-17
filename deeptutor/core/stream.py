"""Deprecated compatibility facade — see ``lumen.runtime.stream.events``.

The unified streaming event protocol (``StreamEvent`` / ``StreamEventType``)
is owned by ``lumen/runtime/stream`` since Phase 6B2.  This module re-exports
it for existing importers and tests only.
"""

from lumen.runtime.stream.events import *  # noqa: F401,F403

__all__ = ["StreamEvent", "StreamEventType"]  # noqa: F405

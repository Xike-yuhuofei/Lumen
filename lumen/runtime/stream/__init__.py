"""Runtime stream subpackage — the unified streaming event protocol + bus.

Since Phase 6B2 (Worker A physical migration) this is the canonical ownership
for streaming infrastructure (``StreamEvent`` / ``StreamBus``).  The legacy
path ``deeptutor.core.stream`` / ``lumen.runtime.stream.bus`` re-exports it so
existing importers keep working.
"""

from lumen.runtime.stream.bus import (
    StreamBus,
    get_bus,
    register_bus,
    unregister_bus,
)
from lumen.runtime.stream.events import StreamEvent, StreamEventType

__all__ = [
    "StreamEvent",
    "StreamEventType",
    "StreamBus",
    "register_bus",
    "unregister_bus",
    "get_bus",
]

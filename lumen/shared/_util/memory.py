"""Private shared util — memory-store access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the canonical memory store
singleton through that private channel.
"""

from __future__ import annotations

from lumen.shared.memory.store import get_memory_store
from lumen.shared.memory.trace import TraceEvent

__all__ = ["TraceEvent", "get_memory_store"]

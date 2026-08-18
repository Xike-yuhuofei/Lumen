"""Private shared util — memory-store access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the canonical memory store
singleton through that private channel.  Names are read through lazily so a
test patching ``lumen.shared.memory.store.get_memory_store`` still takes
effect.
"""

from __future__ import annotations

from lumen.shared.memory import store as _store
from lumen.shared.memory import trace as _trace


def __getattr__(name: str):
    if name == "get_memory_store":
        return _store.get_memory_store
    if name == "TraceEvent":
        return _trace.TraceEvent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

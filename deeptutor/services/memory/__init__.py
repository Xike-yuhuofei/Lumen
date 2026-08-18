"""Deprecated compatibility facade — see ``lumen.shared.memory``."""

from __future__ import annotations

from lumen.shared.memory.contract import MemoryService
from lumen.shared.memory.ids import is_entry_id, is_trace_id, new_entry_id, new_trace_id
from lumen.shared.memory.paths import (
    L3_SLOTS,
    SURFACES,
    L3Slot,
    Surface,
    memory_path_service_override,
)
from lumen.shared.memory.plugin import MemoryPlugin
from lumen.shared.memory.store import (
    DocOverview,
    MemoryStore,
    get_memory_store,
    migrate_v1_if_needed,
)
from lumen.shared.memory.trace import TraceEvent

__all__ = [
    "DocOverview",
    "L3_SLOTS",
    "L3Slot",
    "MemoryPlugin",
    "MemoryService",
    "MemoryStore",
    "SURFACES",
    "Surface",
    "TraceEvent",
    "get_memory_store",
    "is_entry_id",
    "is_trace_id",
    "memory_path_service_override",
    "migrate_v1_if_needed",
    "new_entry_id",
    "new_trace_id",
]
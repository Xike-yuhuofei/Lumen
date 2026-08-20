"""Persistent memory store — read, write, and list memory layers.

This package is the canonical three-layer memory subsystem (migrated from
``lumen.services.memory``, which has been removed).
It also carries the Plugin Kernel contract + adapter plugin.

The canonical implementation modules (``store``, ``document``, ``ops``,
``paths``, ``ids``, ``trace``, ``consolidator``, ``snapshot``) are imported
directly by consumers; this package re-exports only the plugin-kernel contract
+ adapter so importing ``lumen.shared`` stays free of the lumen config /
LLM import chain (no import cycle).
"""

from __future__ import annotations

from lumen.shared.memory.contract import MemoryService
from lumen.shared.memory.plugin import MemoryPlugin

__all__ = ["MemoryService", "MemoryPlugin"]

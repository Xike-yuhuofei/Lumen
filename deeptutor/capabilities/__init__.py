"""Deprecated compatibility facade — see ``lumen.modes.learn``.

Turn-scoped chat-loop capabilities are owned by ``lumen/modes/learn``
(``loop_registry``) plus the ``lumen.runtime.agent_loop.capability`` protocol.
This module re-exports them for existing importers and tests only.
"""
from __future__ import annotations

from lumen.modes.learn.loop_registry import (
    LOOP_CAPABILITIES,
    active_loop_capabilities,
    capability_tool_owners,
)
from lumen.runtime.agent_loop.capability import LoopCapability, PromptBlock

__all__ = [
    "LOOP_CAPABILITIES",
    "LoopCapability",
    "PromptBlock",
    "active_loop_capabilities",
    "capability_tool_owners",
]

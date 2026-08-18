"""Turn-scoped chat-loop capabilities.

Each loop capability lives in its own subpackage under
:mod:`deeptutor.capabilities` (``mastery``). The chat loop imports
only the generic registry/protocol from this package; feature-specific prompts,
tools, and kwargs injection stay inside each capability subpackage.

A loop capability is "chat engine + decoupled capability logic": it reuses the
full chat tool surface and adds its own owned tools + a system prompt block on
top when active, instead of running a bespoke pipeline.
"""

from deeptutor.capabilities.registry import (
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

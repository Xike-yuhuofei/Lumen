"""
Stream Event Protocol (Runtime)
================================

Unified streaming event format used by all tools, capabilities, and agents
to communicate progress and results to consumers (CLI, WebSocket, SDK).

Owned by ``lumen/runtime/stream`` since Phase 6B2 (Worker A physical
migration); ``deeptutor.core.stream`` re-exports it for legacy importers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any


class StreamEventType(str, Enum):
    """All possible event types in a streaming session."""

    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    THINKING = "thinking"
    OBSERVATION = "observation"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"
    SOURCES = "sources"
    RESULT = "result"
    ERROR = "error"
    SESSION = "session"
    SESSION_META = "session_meta"
    DONE = "done"
    WAIT_FOR_INPUT = "wait_for_input"


@dataclass
class StreamEvent:
    """
    A single streaming event emitted during a chat turn.

    Attributes:
        type: The semantic kind of this event.
        source: Which tool / capability / plugin produced it (e.g. "chat").
        stage: Current stage within the source (e.g. "planning").
        content: Human-readable text payload.
        metadata: Arbitrary structured data (tool args, sources, metrics, …).
        timestamp: Unix epoch seconds when the event was created.
    """

    type: StreamEventType
    source: str = ""
    stage: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    seq: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "source": self.source,
            "stage": self.stage,
            "content": self.content,
            "metadata": self.metadata,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
        }


__all__ = [
    "StreamEvent",
    "StreamEventType",
]
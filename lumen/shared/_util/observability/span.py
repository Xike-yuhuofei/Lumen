"""Span record — one unit of telemetry within a turn trace.

``span_id`` is an Observability-only short id. It deliberately does not
share the ID space of the product/UI ``call_id``; a span may carry a
``call_id`` as an attribute to link back to the UI trace card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

__all__ = ["Span"]


@dataclass
class Span:
    """One completed (or in-flight) telemetry span.

    Attributes:
        name: short span name (``turn`` / ``agent_loop`` / ``llm_call`` / …).
        kind: span category (``turn`` / ``agent_loop`` / …).
        trace_id: telemetry trace id (independent of the domain ``turn_id``).
        span_id: observability-only span id.
        parent_span_id: parent span id (None for the trace root).
        started_at: monotonic start timestamp.
        duration: seconds, filled by the span machinery on finish.
        attrs: sanitized metadata (no user content, no secrets).
        call_id: optional product/UI call id used to link back to the stream
            trace card.
    """

    name: str
    kind: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_at: float = field(default_factory=time.monotonic)
    duration: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "started_at": self.started_at,
            "duration": self.duration,
            "attrs": self.attrs,
            "call_id": self.call_id,
        }

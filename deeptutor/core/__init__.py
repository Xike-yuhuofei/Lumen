"""Core contracts shared across runtime, tools, and capabilities."""

from lumen.runtime.stream.bus import StreamBus

from .context import Attachment, UnifiedContext
from .stream import StreamEvent, StreamEventType
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)
from .trace import build_trace_metadata, merge_trace_metadata, new_call_id

__all__ = [
    "StreamEvent",
    "StreamEventType",
    "StreamBus",
    "new_call_id",
    "build_trace_metadata",
    "merge_trace_metadata",
    "BaseTool",
    "ToolAlias",
    "ToolDefinition",
    "ToolParameter",
    "ToolPromptHints",
    "ToolResult",
    "UnifiedContext",
    "Attachment",
]

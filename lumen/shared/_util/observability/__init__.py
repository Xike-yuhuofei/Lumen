"""Observability infrastructure (v1) — stable contract for all lumen layers.

Owned by ``lumen/shared/_util/observability`` (private shared utility
namespace, consumable by runtime / modes / app without violating the
Architecture Gates). Business modules depend only on the functions here,
never on a specific telemetry backend.

Round-1 scope (Observability Architecture v1): correlation context, span
records, in-process metrics, redaction, and a swappable backend (no-op by
default; local JSONL in production).

See ``docs/architecture/observability-architecture-v1.md`` for the frozen
architecture decisions.
"""

from .backend import (
    DEFAULT_TELEMETRY_RETENTION_DAYS,
    LocalBackend,
    NoopBackend,
    TelemetryBackend,
    configure,
    get_backend,
    set_backend,
)
from .context import (
    begin_request,
    begin_span,
    current_parent_span_id,
    current_request_id,
    current_span_id,
    current_spans,
    current_trace_id,
    end_request,
    finish_span,
    new_request_id,
    new_span_id,
    new_trace_id,
    trace_span,
)
from .instrument import span
from .metrics import (
    MetricsRecorder,
    MetricsSnapshot,
    get_metrics,
    increment,
    observe,
    reset_metrics,
)
from .redact import REDACTED, sanitize_attrs, sanitize_text
from .span import Span

__all__ = [
    # ids
    "new_trace_id",
    "new_span_id",
    "new_request_id",
    # context / spans
    "begin_span",
    "finish_span",
    "trace_span",
    "begin_request",
    "end_request",
    "current_trace_id",
    "current_span_id",
    "current_parent_span_id",
    "current_request_id",
    "current_spans",
    # backend
    "TelemetryBackend",
    "NoopBackend",
    "LocalBackend",
    "get_backend",
    "set_backend",
    "configure",
    "DEFAULT_TELEMETRY_RETENTION_DAYS",
    # instrumentation helper
    "span",
    # metrics
    "MetricsRecorder",
    "MetricsSnapshot",
    "get_metrics",
    "increment",
    "observe",
    "reset_metrics",
    # redaction
    "REDACTED",
    "sanitize_attrs",
    "sanitize_text",
    # data types
    "Span",
]

"""OpenTelemetry (OTLP/HTTP, JSON encoding) trace exporter (Candidate 3).

Exports completed telemetry spans to any OTLP-compatible collector
(OpenTelemetry Collector, Phoenix, …) using the standard OTLP/HTTP **JSON**
encoding — no OpenTelemetry SDK or protobuf dependency is required. The
payload is built by hand from the frozen C1/C2 :class:`Span` model and posted
with ``httpx`` (already a core dependency).

Semantics:

* Standard OTLP Trace fields: ``traceId`` (16-byte hex), ``spanId`` (8-byte
  hex), ``parentSpanId``, ``name``, ``kind``, ``startTimeUnixNano`` /
  ``endTimeUnixNano``, ``attributes``, ``status`` — the existing Lumen
  correlation ids stay traceable as span attributes (``lumen.trace_id`` /
  ``lumen.call_id`` / ``turn_id`` / ``session_id``).
* OpenInference semantic-convention attributes are attached on AI/agent spans
  (``openinference.span.kind`` = LLM / TOOL / RETRIEVER / AGENT / CHAIN plus
  safe ``llm.model_name`` / ``llm.token_count.*`` / ``tool.name`` /
  ``retrieval.*``) so AI-observability backends such as Phoenix render the
  LLM / agent / tool / retrieval path correctly — without the Phoenix SDK.
* No user content is exported: spans are already redacted at ``finish_span``
  and re-sanitized by ``dispatch_span``; prompt/response bodies are never
  attached as attributes.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Sequence

import httpx

from .exporter import TelemetryExporter
from .redact import sanitize_attrs
from .span import Span

__all__ = ["OtlpSpanExporter", "build_trace_request", "convert_span"]

# OTLP/HTTP JSON content type.
_JSON_CONTENT_TYPE = "application/json"

# OpenTelemetry SpanKind enum values (no SDK dependency).
_SPAN_KIND_INTERNAL = 1
_SPAN_KIND_SERVER = 2
_SPAN_KIND_CLIENT = 3

# OpenInference semantic-convention span kinds (subset used by Lumen).
_OI_LLM = "LLM"
_OI_TOOL = "TOOL"
_OI_RETRIEVER = "RETRIEVER"
_OI_AGENT = "AGENT"
_OI_CHAIN = "CHAIN"

#: Lumen span ``kind`` → OpenInference span kind (None = plain span).
#: The LLM spans opened by the engine-client seam and the LLM provider core
#: use ``kind="llm"`` (span name ``llm_call``), so both spellings must map to
#: the same OpenInference ``LLM`` kind (C2/F1: kind alignment).
_OPENINFERENCE_KIND = {
    "llm": _OI_LLM,
    "llm_call": _OI_LLM,
    "tool": _OI_TOOL,
    "retrieval": _OI_RETRIEVER,
    "agent_loop": _OI_AGENT,
    "turn": _OI_CHAIN,
    "teaching_decision": _OI_CHAIN,
    "teaching_commit": _OI_CHAIN,
}


def _otel_kind(kind: str) -> int:
    """Map a Lumen span kind to an OpenTelemetry SpanKind."""
    if kind in ("llm", "llm_call"):
        # LLM calls are outbound client calls.
        return _SPAN_KIND_CLIENT
    return _SPAN_KIND_INTERNAL


def _openinference_kind(kind: str) -> str | None:
    return _OPENINFERENCE_KIND.get(kind)


def _openinference_attrs(span: Span, attrs: dict[str, Any]) -> dict[str, Any]:
    """Attach safe OpenInference semantic-convention attributes."""
    oi_kind = _openinference_kind(span.kind)
    if oi_kind is not None:
        attrs["openinference.span.kind"] = oi_kind
    if span.kind in ("llm", "llm_call"):
        if "model" in attrs:
            attrs["llm.model_name"] = attrs["model"]
        for src, dst in (
            ("prompt_tokens", "llm.token_count.prompt"),
            ("completion_tokens", "llm.token_count.completion"),
        ):
            if src in attrs:
                attrs[dst] = attrs[src]
    elif span.kind == "tool" and "tool" in attrs:
        attrs["tool.name"] = attrs["tool"]
    elif span.kind == "retrieval":
        if "query" in attrs:
            attrs["retrieval.query"] = attrs["query"]
        if "kb_name" in attrs:
            attrs["retrieval.knowledge_base"] = attrs["kb_name"]
    return attrs


def _otlp_value(value: Any) -> dict[str, Any]:
    """Encode a Python scalar as an OTLP ``AnyValue``."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def convert_span(span: Span, end_ns: int) -> dict[str, Any]:
    """Convert one finished :class:`Span` to an OTLP/HTTP JSON span object.

    ``end_ns`` is the wall-clock finish time in nanoseconds (captured at
    export time); the start time is derived from the span duration so the
    local monotonic clock never leaks into the exported payload.
    """
    attrs = _openinference_attrs(span, dict(span.attrs))
    attrs = sanitize_attrs(attrs)
    duration_ns = max(0, int(span.duration * 1_000_000_000))
    status_code = 1 if attrs.get("status") == "error" else 0
    return {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "parentSpanId": span.parent_span_id or "",
        "name": span.name,
        "kind": _otel_kind(span.kind),
        "startTimeUnixNano": str(max(0, end_ns - duration_ns)),
        "endTimeUnixNano": str(end_ns),
        "attributes": [
            {"key": str(key), "value": _otlp_value(value)} for key, value in attrs.items()
        ],
        "status": {"code": status_code},
        "droppedAttributesCount": 0,
    }


def build_trace_request(span_objects: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Wrap converted span objects into an OTLP ``ExportTraceServiceRequest``."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "lumen"}}
                    ],
                    "droppedAttributesCount": 0,
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "lumen.observability", "version": "1.0.0"},
                        "spans": list(span_objects),
                    }
                ],
            }
        ]
    }


class OtlpSpanExporter(TelemetryExporter):
    """Batch OTLP/HTTP trace exporter.

    ``export_span`` only buffers a converted payload (O(1), never performs
    network I/O inline). A flush is triggered when the batch reaches
    ``batch_size``, or explicitly via :meth:`flush` / :meth:`shutdown` / the
    background flusher. Failures are isolated: a dead or unreachable backend
    makes ``flush`` return ``False`` (counted as ``export.otlp.errors``)
    without raising, and the batch is dropped (safe degradation — telemetry
    is never allowed to block the producer).
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:4318/v1/traces",
        headers: dict[str, str] | None = None,
        batch_size: int = 64,
        timeout_seconds: float = 3.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._headers = {"Content-Type": _JSON_CONTENT_TYPE, **(headers or {})}
        self._batch_size = max(1, int(batch_size))
        self._timeout = max(0.1, float(timeout_seconds))
        self._client = http_client or httpx.Client(timeout=self._timeout)
        self._lock = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._closed = False
        #: Counters for diagnostics / tests.
        self.spans_sent = 0
        self.failed_flushes = 0

    def export_span(self, span: Span) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._queue.append(convert_span(span, time.time_ns()))
            force_flush = len(self._queue) >= self._batch_size
        if force_flush:
            return self.flush()
        return True

    def flush(self) -> bool:
        with self._lock:
            batch = self._queue
            self._queue = []
        if not batch:
            return True
        body = build_trace_request(batch)
        try:
            response = self._client.post(self._endpoint, json=body, headers=self._headers)
            ok = 200 <= response.status_code < 400
        except Exception:
            ok = False
        if ok:
            self.spans_sent += len(batch)
        else:
            self.failed_flushes += 1
        return ok

    def export_metrics(self, snapshot: Any) -> bool:
        # OTLP Metrics export is a documented extension point; Candidate 3
        # ships the stable periodic summary path (metrics_export.py) instead
        # of hand-rolling the OTLP metrics wire format.
        return True

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.flush()
        except Exception:  # pragma: no cover
            pass
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            pass

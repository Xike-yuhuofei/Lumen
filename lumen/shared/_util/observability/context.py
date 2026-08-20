"""Request/turn/span telemetry context.

A single contextvars state carries the active ``trace_id``, ``span_id`` and
``request_id`` plus the span stack, so nested spans (turn → agent_loop →
llm/tool/…) form a parent chain. Every ``begin_span`` / ``begin_request``
also pins the correlation fields into the logging context, so log records
emitted inside the span automatically carry ``trace_id / span_id / turn_id``
without touching the logging pipeline.

Propagation: contextvars copy into ``asyncio.create_task`` contexts on Python
>= 3.11, so background tasks spawned inside a turn inherit the trace.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import contextvars
import time
from typing import Any
from uuid import uuid4

from lumen.shared._util.logging.context import restore_log_context, set_log_context

from .backend import get_backend
from .redact import sanitize_attrs
from .span import Span

__all__ = [
    "new_trace_id",
    "new_span_id",
    "new_request_id",
    "current_trace_id",
    "current_span_id",
    "current_parent_span_id",
    "current_request_id",
    "current_spans",
    "begin_span",
    "finish_span",
    "trace_span",
    "begin_request",
    "end_request",
]

#: token pair produced by begin_span / begin_request.
SpanToken = tuple[contextvars.Token[dict[str, Any] | None], contextvars.Token[dict[str, Any]]]

_telemetry: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "lumen_telemetry", default=None
)


def new_trace_id() -> str:
    """Telemetry trace id — 32 hex chars (16 bytes), OTEL/W3C compatible."""
    return uuid4().hex


def new_span_id() -> str:
    """Observability-only span id — 16 hex chars (8 bytes)."""
    return uuid4().hex[:16]


def new_request_id() -> str:
    """Entry request id (HTTP / WS)."""
    return uuid4().hex[:16]


def _tele() -> dict[str, Any]:
    return _telemetry.get() or {}


def current_trace_id() -> str | None:
    tele = _tele()
    return tele.get("trace_id")


def current_span_id() -> str | None:
    tele = _tele()
    return tele.get("span_id")


def current_parent_span_id() -> str | None:
    tele = _tele()
    return tele.get("parent_span_id")


def current_request_id() -> str | None:
    tele = _tele()
    return tele.get("request_id")


def current_spans() -> list[Span]:
    """Active span stack (innermost last). Read-only copy for tests/tools."""
    return list(_tele().get("spans", []))


def begin_span(
    name: str,
    *,
    kind: str = "turn",
    trace_id: str | None = None,
    attrs: dict[str, Any] | None = None,
    bind: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> tuple[Span, SpanToken]:
    """Open a span, push it onto the stack, and pin correlation log fields.

    Returns ``(span, token)``; pair with :func:`finish_span` (or use the
    :func:`trace_span` context manager). ``trace_id`` defaults to the current
    trace (or a fresh one when none is active). Extra ``bind`` fields are
    merged into the logging context (e.g. ``turn_id`` / ``session_id``).
    """
    tele = _tele()
    parent_span_id = tele.get("span_id")
    effective_trace = trace_id or tele.get("trace_id") or new_trace_id()
    span = Span(
        name=name,
        kind=kind,
        trace_id=effective_trace,
        span_id=new_span_id(),
        parent_span_id=parent_span_id,
        attrs=dict(attrs or {}),
        call_id=call_id,
    )
    fields: dict[str, Any] = {
        "trace_id": effective_trace,
        "span_id": span.span_id,
        "parent_span_id": parent_span_id,
    }
    if tele.get("request_id"):
        fields["request_id"] = tele["request_id"]
    if bind:
        fields.update({key: value for key, value in bind.items() if value is not None})

    new_tele = {
        "trace_id": effective_trace,
        "span_id": span.span_id,
        "parent_span_id": parent_span_id,
        "request_id": tele.get("request_id"),
        "spans": [*tele.get("spans", []), span],
    }
    tele_token = _telemetry.set(new_tele)
    log_token = set_log_context(**fields)
    return span, (tele_token, log_token)


def finish_span(span: Span, token: SpanToken) -> None:
    """Close *span* (records duration + sanitized attrs) and restore context."""
    span.duration = max(0.0, time.monotonic() - span.started_at)
    # Sanitize at the canonical boundary so no backend ever sees raw secrets.
    span.attrs = sanitize_attrs(span.attrs)
    tele_token, log_token = token
    try:
        get_backend().record_span(span)
    except Exception:  # pragma: no cover - telemetry must never break the caller
        pass
    _telemetry.reset(tele_token)
    restore_log_context(log_token)


@contextmanager
def trace_span(name: str, **kwargs: Any) -> Iterator[Span]:
    """Context manager form of :func:`begin_span` / :func:`finish_span`."""
    span, token = begin_span(name, **kwargs)
    try:
        yield span
    finally:
        finish_span(span, token)


def begin_request(request_id: str | None = None) -> SpanToken:
    """Bind an entry-level *request_id* for the current scope.

    Usually called at the HTTP/WS entry; the id propagates into any turn
    started within the scope (contextvars copy into child tasks).
    """
    rid = request_id or new_request_id()
    tele = _tele()
    new_tele = {**tele, "request_id": rid}
    tele_token = _telemetry.set(new_tele)
    log_token = set_log_context(request_id=rid)
    return (tele_token, log_token)


def end_request(token: SpanToken) -> None:
    """Restore context after :func:`begin_request`."""
    tele_token, log_token = token
    _telemetry.reset(tele_token)
    restore_log_context(log_token)

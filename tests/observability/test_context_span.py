"""Observability span/trace/request context tests."""

from __future__ import annotations

import asyncio

from lumen.shared._util.logging import current_log_context
from lumen.shared._util.observability import (
    NoopBackend,
    begin_request,
    begin_span,
    current_request_id,
    current_span_id,
    current_spans,
    current_trace_id,
    end_request,
    finish_span,
    new_request_id,
    new_trace_id,
    set_backend,
)


class _SpyBackend(NoopBackend):
    """Records spans handed to the backend."""

    def __init__(self) -> None:
        self.spans = []

    def record_span(self, span) -> None:
        self.spans.append(span)


def test_nested_spans_share_trace_and_chain_parents():
    set_backend(NoopBackend())
    outer, tok1 = begin_span("turn", kind="turn", trace_id=new_trace_id())
    try:
        assert current_trace_id() == outer.trace_id
        assert current_span_id() == outer.span_id
        inner, tok2 = begin_span("agent_loop", kind="agent_loop")
        try:
            assert inner.trace_id == outer.trace_id
            assert inner.parent_span_id == outer.span_id
            assert current_span_id() == inner.span_id
            assert len(current_spans()) == 2
        finally:
            finish_span(inner, tok2)
        assert current_span_id() == outer.span_id
        assert len(current_spans()) == 1
    finally:
        finish_span(outer, tok1)
    assert current_trace_id() is None
    assert current_span_id() is None
    assert current_spans() == []


def test_span_without_explicit_trace_generates_one():
    set_backend(NoopBackend())
    span, token = begin_span("turn", kind="turn")
    try:
        assert span.trace_id
        assert current_trace_id() == span.trace_id
    finally:
        finish_span(span, token)


def test_span_binds_correlation_into_log_context():
    set_backend(NoopBackend())
    span, token = begin_span(
        "turn",
        kind="turn",
        trace_id=new_trace_id(),
        bind={"turn_id": "turn-abc", "session_id": "session-1"},
    )
    try:
        ctx = current_log_context()
        assert ctx["trace_id"] == span.trace_id
        assert ctx["span_id"] == span.span_id
        assert ctx["turn_id"] == "turn-abc"
        assert ctx["session_id"] == "session-1"
    finally:
        finish_span(span, token)
    restored = current_log_context()
    assert "trace_id" not in restored
    assert "turn_id" not in restored


def test_async_task_inherits_telemetry_context():
    set_backend(NoopBackend())

    async def inner():
        return current_trace_id(), current_span_id()

    async def outer():
        span, token = begin_span("turn", kind="turn", trace_id=new_trace_id())
        try:
            trace_id, span_id = await asyncio.create_task(inner())
            assert trace_id == span.trace_id
            assert span_id == span.span_id
        finally:
            finish_span(span, token)

    asyncio.run(outer())


def test_backend_receives_sanitized_finished_span():
    spy = _SpyBackend()
    set_backend(spy)
    span, token = begin_span(
        "turn",
        kind="turn",
        trace_id=new_trace_id(),
        attrs={"capability": "chat", "api_key": "sk-should-not-leak"},
    )
    finish_span(span, token)
    assert len(spy.spans) == 1
    recorded = spy.spans[0]
    assert recorded.name == "turn"
    assert recorded.trace_id == span.trace_id
    assert recorded.attrs["api_key"] == "[REDACTED]"
    assert recorded.attrs["capability"] == "chat"


def test_noop_backend_never_raises():
    set_backend(NoopBackend())
    span, token = begin_span("turn", kind="turn")
    finish_span(span, token)  # must not raise


def test_request_id_binds_and_restores():
    set_backend(NoopBackend())
    assert current_request_id() is None
    rid = new_request_id()
    token = begin_request(rid)
    try:
        assert current_request_id() == rid
        assert current_log_context()["request_id"] == rid
        # a span started inside the request inherits the request_id
        span, span_token = begin_span("turn", kind="turn")
        try:
            assert current_request_id() == rid
            assert current_log_context()["request_id"] == rid
        finally:
            finish_span(span, span_token)
    finally:
        end_request(token)
    assert current_request_id() is None

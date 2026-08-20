"""Candidate 3 OTLP exporter tests — payload semantics + HTTP export.

Verifies the hand-rolled OTLP/HTTP JSON exporter: standard trace/span fields,
OpenInference attribute mapping for AI spans, redaction at the export
boundary, batching, and safe degradation when the collector is unreachable.
"""

from __future__ import annotations

import json

import httpx
import pytest

from lumen.shared._util.observability import Span
from lumen.shared._util.observability.otlp import (
    OtlpSpanExporter,
    build_trace_request,
    build_trace_request_protobuf,
    convert_span,
)


def _span(
    name: str = "turn",
    kind: str = "turn",
    *,
    parent: str | None = None,
    attrs: dict | None = None,
) -> Span:
    return Span(
        name=name,
        kind=kind,
        trace_id="0" * 32,
        span_id="1" * 16,
        parent_span_id=parent,
        attrs=attrs or {},
        call_id="call-1",
    )


def _attr_map(span_obj: dict) -> dict[str, dict]:
    return {a["key"]: a["value"] for a in span_obj["attributes"]}


# ── payload semantics ──────────────────────────────────────────────────────


def test_convert_span_builds_standard_otlp_fields():
    out = convert_span(_span(), end_ns=1_000_000_000)
    assert out["traceId"] == "0" * 32
    assert out["spanId"] == "1" * 16
    assert out["parentSpanId"] == ""
    assert out["name"] == "turn"
    assert out["kind"] == 1  # INTERNAL
    assert out["endTimeUnixNano"] == "1000000000"
    assert out["status"]["code"] == 0


def test_convert_span_preserves_parent_and_llm_kind():
    out = convert_span(
        _span(name="llm_call", kind="llm_call", parent="9" * 16), end_ns=1_000_000_000
    )
    assert out["parentSpanId"] == "9" * 16
    assert out["kind"] == 3  # CLIENT (LLM calls are outbound)


def test_convert_span_marks_error_status():
    out = convert_span(_span(attrs={"status": "error"}), end_ns=1_000_000_000)
    assert out["status"]["code"] == 1


def test_convert_span_derives_start_from_duration():
    span = _span()
    span.duration = 0.5
    out = convert_span(span, end_ns=1_000_000_000)
    assert out["startTimeUnixNano"] == "500000000"


# ── OpenInference mapping ──────────────────────────────────────────────────


def test_llm_span_gets_openinference_attrs():
    out = convert_span(
        _span(
            name="llm_call",
            kind="llm_call",
            attrs={"model": "gpt-4", "prompt_tokens": 10, "completion_tokens": 5},
        ),
        end_ns=1_000_000_000,
    )
    attrs = _attr_map(out)
    assert attrs["openinference.span.kind"] == {"stringValue": "LLM"}
    assert attrs["llm.model_name"] == {"stringValue": "gpt-4"}
    assert attrs["llm.token_count.prompt"] == {"intValue": 10}
    assert attrs["llm.token_count.completion"] == {"intValue": 5}


def test_llm_kind_alias_maps_to_llm_and_client():
    """LLM spans opened with ``kind="llm"`` (engine-client seam + provider
    core) must render as OpenInference ``LLM`` nodes with ``CLIENT`` OTEL
    kind, matching the ``llm_call`` spelling (C2/F1 kind alignment)."""
    out = convert_span(
        _span(
            name="llm_call",
            kind="llm",
            attrs={"model": "gpt-4", "prompt_tokens": 10, "completion_tokens": 5},
        ),
        end_ns=1_000_000_000,
    )
    assert out["kind"] == 3  # CLIENT (LLM calls are outbound)
    attrs = _attr_map(out)
    assert attrs["openinference.span.kind"] == {"stringValue": "LLM"}
    assert attrs["llm.model_name"] == {"stringValue": "gpt-4"}
    assert attrs["llm.token_count.prompt"] == {"intValue": 10}
    assert attrs["llm.token_count.completion"] == {"intValue": 5}


def test_tool_and_retrieval_and_agent_kinds():
    tool = _attr_map(
        convert_span(
            _span(name="tool", kind="tool", attrs={"tool": "web_search"}),
            end_ns=1_000_000_000,
        )
    )
    assert tool["openinference.span.kind"] == {"stringValue": "TOOL"}
    assert tool["tool.name"] == {"stringValue": "web_search"}

    retr = _attr_map(
        convert_span(
            _span(
                name="retrieval",
                kind="retrieval",
                attrs={"query": "what is x", "kb_name": "kb1"},
            ),
            end_ns=1_000_000_000,
        )
    )
    assert retr["openinference.span.kind"] == {"stringValue": "RETRIEVER"}
    assert retr["retrieval.query"] == {"stringValue": "what is x"}
    assert retr["retrieval.knowledge_base"] == {"stringValue": "kb1"}

    agent = _attr_map(
        convert_span(_span(name="agent_loop", kind="agent_loop"), end_ns=1_000_000_000)
    )
    assert agent["openinference.span.kind"] == {"stringValue": "AGENT"}


def test_persistence_span_stays_plain():
    attrs = _attr_map(
        convert_span(_span(name="persistence", kind="persistence"), end_ns=1_000_000_000)
    )
    assert "openinference.span.kind" not in attrs


# ── redaction at the export boundary ───────────────────────────────────────


def test_convert_span_redacts_secrets():
    out = convert_span(
        _span(
            attrs={
                "api_key": "sk-leak",
                "authorization": "Bearer abcdef0123456789",
                "prompt_tokens": 10,  # numeric metric must survive
            }
        ),
        end_ns=1_000_000_000,
    )
    attrs = _attr_map(out)
    assert attrs["api_key"] == {"stringValue": "[REDACTED]"}
    assert attrs["authorization"] == {"stringValue": "[REDACTED]"}
    assert attrs["prompt_tokens"] == {"intValue": 10}


def test_build_trace_request_wraps_resource_and_scope():
    body = build_trace_request([convert_span(_span(), end_ns=1)])
    resource = body["resourceSpans"][0]["resource"]
    assert resource["attributes"][0] == {
        "key": "service.name",
        "value": {"stringValue": "lumen"},
    }
    scope = body["resourceSpans"][0]["scopeSpans"][0]
    assert scope["scope"]["name"] == "lumen.observability"
    assert len(scope["spans"]) == 1


# ── HTTP export / batching / degradation ───────────────────────────────────


def test_exporter_posts_otlp_json_via_http():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.read()
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exporter = OtlpSpanExporter(
        endpoint="http://localhost:4318/v1/traces",
        batch_size=2,
        http_client=client,
    )
    try:
        assert exporter.export_span(_span()) is True
        assert exporter.export_span(_span()) is True  # triggers batch flush
        assert captured, "no HTTP request was made"
        assert captured["url"] == "http://localhost:4318/v1/traces"
        assert captured["content_type"] == "application/json"
        body = json.loads(captured["body"])
        spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 2
        assert exporter.spans_sent == 2
        assert exporter.failed_flushes == 0
    finally:
        exporter.shutdown()


# ── protobuf encoding (Phoenix-compatible wire format) ─────────────────────


def test_build_trace_request_protobuf_serializes_spans():
    """protobuf encoding must serialize the same converted spans and be
    decodable back to the standard OTLP protobuf model (round-trip)."""
    out = build_trace_request_protobuf(
        [
            convert_span(
                _span(
                    name="llm_call",
                    kind="llm",
                    attrs={"model": "gpt-4", "prompt_tokens": 10, "completion_tokens": 5},
                ),
                end_ns=1_000_000_000,
            )
        ]
    )
    if out is None:
        pytest.skip("opentelemetry-proto not installed")

    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    request = ExportTraceServiceRequest()
    request.ParseFromString(out)
    assert len(request.resource_spans) == 1
    resource = request.resource_spans[0]
    assert resource.resource.attributes[0].key == "service.name"
    assert resource.resource.attributes[0].value.string_value == "lumen"
    scope = resource.scope_spans[0]
    assert scope.scope.name == "lumen.observability"
    assert len(scope.spans) == 1
    span = scope.spans[0]
    assert span.name == "llm_call"
    assert span.kind == 3  # CLIENT
    attrs = {a.key: a.value for a in span.attributes}
    assert attrs["openinference.span.kind"].string_value == "LLM"
    assert attrs["llm.model_name"].string_value == "gpt-4"
    assert attrs["llm.token_count.prompt"].int_value == 10
    assert attrs["llm.token_count.completion"].int_value == 5


def test_exporter_posts_otlp_protobuf_via_http():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.read()
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exporter = OtlpSpanExporter(
        endpoint="http://localhost:4318/v1/traces",
        batch_size=1,
        http_client=client,
        encoding="protobuf",
    )
    try:
        assert exporter.export_span(_span()) is True
        assert captured, "no HTTP request was made"
        assert captured["url"] == "http://localhost:4318/v1/traces"
        assert captured["content_type"] == "application/x-protobuf"
        assert isinstance(captured["body"], bytes)
        assert len(captured["body"]) > 0
        assert exporter.spans_sent == 1
        assert exporter.failed_flushes == 0
    finally:
        exporter.shutdown()


def test_exporter_defaults_to_json_encoding():
    exporter = OtlpSpanExporter(
        batch_size=1,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        ),
    )
    try:
        assert exporter._encoding == "json"
        assert exporter._headers["Content-Type"] == "application/json"
    finally:
        exporter.shutdown()


def test_exporter_buffers_until_batch_size():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        sent.append(body)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exporter = OtlpSpanExporter(batch_size=5, http_client=client)
    try:
        for _ in range(4):
            exporter.export_span(_span())
        assert sent == []  # nothing sent below the batch threshold
        exporter.export_span(_span())  # 5th span triggers flush
        assert len(sent) == 1
        assert len(sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 5
    finally:
        exporter.shutdown()


def test_shutdown_flushes_remaining_and_closes():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.read()))
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exporter = OtlpSpanExporter(batch_size=100, http_client=client)
    exporter.export_span(_span())
    exporter.export_span(_span())
    exporter.shutdown()
    assert len(sent) == 1
    assert len(sent[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 2


def test_unreachable_collector_degrades_safely():
    exporter = OtlpSpanExporter(
        endpoint="http://127.0.0.1:1/v1/traces",
        batch_size=1,
        timeout_seconds=0.2,
    )
    try:
        # Must not raise; reports failure so the dispatcher counts an error.
        assert exporter.export_span(_span()) is False
        assert exporter.failed_flushes >= 1
        # Subsequent exports keep failing gracefully, never raise.
        exporter.export_span(_span())
    finally:
        exporter.shutdown()


def test_non_2xx_response_counts_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    exporter = OtlpSpanExporter(batch_size=1, http_client=client)
    try:
        assert exporter.export_span(_span()) is False
        assert exporter.failed_flushes == 1
    finally:
        exporter.shutdown()

"""Optional OTLP/HTTP protobuf wire encoding (Phoenix / OTel Collector).

Kept in a separate module so :mod:`otlp` — the frozen, dependency-free OTLP
exporter — never imports an external observability SDK. ``opentelemetry.proto``
is an optional dependency, imported lazily: when it is not installed the
protobuf encoding is unavailable and the exporter falls back to JSON.
"""

from __future__ import annotations

from typing import Any, Sequence

__all__ = ["build_trace_request_protobuf", "is_protobuf_available"]

#: Cached module for ``opentelemetry.proto`` (optional dependency). ``None``
#: while uninitialised; ``False`` when the package is not installed.
_OPENTELEMETRY_PROTO = None


def _load_opentelemetry_proto():
    """Import the OTel protobuf types lazily (``None`` if unavailable)."""
    global _OPENTELEMETRY_PROTO
    if _OPENTELEMETRY_PROTO is None:
        try:
            from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
            from opentelemetry.proto.common.v1 import common_pb2
            from opentelemetry.proto.resource.v1 import resource_pb2
            from opentelemetry.proto.trace.v1 import trace_pb2

            _OPENTELEMETRY_PROTO = {
                "trace_service": trace_service_pb2,
                "common": common_pb2,
                "resource": resource_pb2,
                "trace": trace_pb2,
            }
        except Exception:  # pragma: no cover - environment dependent
            _OPENTELEMETRY_PROTO = False
    return _OPENTELEMETRY_PROTO or None


def is_protobuf_available() -> bool:
    """Whether the optional ``opentelemetry.proto`` dependency is installed."""
    return _load_opentelemetry_proto() is not None


def _to_protobuf_value(proto_common: Any, value: Any) -> Any:
    """Encode a Python scalar as an OTLP ``AnyValue`` (protobuf flavour)."""
    any_value = proto_common.AnyValue()
    if isinstance(value, bool):
        any_value.bool_value = value
    elif isinstance(value, int):
        any_value.int_value = value
    elif isinstance(value, float):
        any_value.double_value = value
    else:
        any_value.string_value = str(value)
    return any_value


def build_trace_request_protobuf(span_objects: Sequence[dict[str, Any]]) -> bytes | None:
    """Serialize converted span objects to an OTLP protobuf request body.

    Returns ``None`` when the optional ``opentelemetry.proto`` package is not
    installed (caller falls back to JSON).
    """
    proto = _load_opentelemetry_proto()
    if proto is None:
        return None
    common = proto["common"]
    trace = proto["trace"]
    resource = proto["resource"]
    service = proto["trace_service"]

    spans = []
    for obj in span_objects:
        span = trace.Span(
            trace_id=bytes.fromhex(obj["traceId"]),
            span_id=bytes.fromhex(obj["spanId"]),
            name=obj["name"],
            kind=obj["kind"],
            start_time_unix_nano=int(obj["startTimeUnixNano"]),
            end_time_unix_nano=int(obj["endTimeUnixNano"]),
            dropped_attributes_count=obj.get("droppedAttributesCount", 0),
        )
        parent = obj.get("parentSpanId")
        if parent:
            span.parent_span_id = bytes.fromhex(parent)
        status = obj.get("status") or {}
        span.status.code = int(status.get("code", 0))
        for attr in obj.get("attributes") or []:
            raw_value = attr["value"]
            if "stringValue" in raw_value:
                value = raw_value["stringValue"]
            elif "intValue" in raw_value:
                value = raw_value["intValue"]
            elif "doubleValue" in raw_value:
                value = raw_value["doubleValue"]
            elif "boolValue" in raw_value:
                value = raw_value["boolValue"]
            else:
                value = str(raw_value)
            span.attributes.append(
                common.KeyValue(
                    key=str(attr["key"]),
                    value=_to_protobuf_value(common, value),
                )
            )
        spans.append(span)

    request = service.ExportTraceServiceRequest(
        resource_spans=[
            trace.ResourceSpans(
                resource=resource.Resource(
                    attributes=[
                        common.KeyValue(
                            key="service.name",
                            value=common.AnyValue(string_value="lumen"),
                        )
                    ]
                ),
                scope_spans=[
                    trace.ScopeSpans(
                        scope=common.InstrumentationScope(
                            name="lumen.observability", version="1.0.0"
                        ),
                        spans=spans,
                    )
                ],
            )
        ]
    )
    return request.SerializeToString()

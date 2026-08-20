"""Thin instrumentation helpers used at execution boundaries.

Combines a telemetry span with metric recording so instrumentation points
stay one-liners and never break the producer:

* ``span(...)`` opens a named span (nested under the current trace),
  auto-records ``<metric>.latency`` and ``<metric>.total`` when ``metric``
  is given, and marks ``attrs["status"]`` from ``status`` on exit.
* Callers increment ``<metric>.errors`` explicitly when they observe an
  error/failed result (the span helper cannot know the business outcome).

Logs / Traces / Metrics stay independent signals correlated via
``trace_id / span_id`` (see Observability Architecture v1).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .context import begin_span, finish_span
from .metrics import increment, observe
from .span import Span

__all__ = ["span"]


@contextmanager
def span(
    name: str,
    *,
    kind: str = "span",
    attrs: dict[str, Any] | None = None,
    bind: dict[str, Any] | None = None,
    metric: str | None = None,
    status: str = "ok",
    trace_id: str | None = None,
    call_id: str | None = None,
) -> Iterator[Span]:
    """Open a telemetry span, record latency/total metrics, and close it.

    On normal exit the span's ``attrs["status"]`` is set to *status* (default
    ``"ok"``). If the body raises, the span is still closed, ``attrs["status"]``
    is ``"error"`` and the exception propagates; ``<metric>.errors`` is
    incremented when ``metric`` is given. Redaction runs at ``finish_span``.
    """
    span_obj, token = begin_span(
        name,
        kind=kind,
        attrs=attrs,
        bind=bind,
        trace_id=trace_id,
        call_id=call_id,
    )
    error = False
    try:
        yield span_obj
    except BaseException:
        error = True
        raise
    finally:
        if error:
            # Exceptions always mark the span failed regardless of body attrs.
            span_obj.attrs["status"] = "error"
        elif "status" not in span_obj.attrs:
            # The body may pre-set a business-failure status (e.g. a tool that
            # returned success=False); only default to *status* when unset.
            span_obj.attrs["status"] = status
        finish_span(span_obj, token)
        if metric:
            observe(f"{metric}.latency", span_obj.duration)
            increment(f"{metric}.total")
            if error:
                increment(f"{metric}.errors")

"""Pluggable telemetry exporters for external observation backends (Candidate 3).

Trace / Metrics produced by the local pipeline (Observability Architecture v1,
Candidates 1 & 2) can be fanned out to OPTIONAL external exporters. The design
keeps the frozen contract intact:

* Business modules only consume the local contract from ``__init__``; they
  never import an exporter and never know which backend is attached.
* Exporters are OPTIONAL and local-first. With no configuration the registry
  is empty and ``dispatch_span`` / ``flush_metrics`` are near-free no-ops, so
  an unconfigured process behaves exactly like Candidates 1 & 2.
* Every external exit is best-effort and isolated: one failing exporter can
  never raise into the producing code path and never blocks another exporter.
* Redaction runs at ``finish_span`` (canonical boundary) and is re-applied by
  ``dispatch_span`` before a span is handed to any exporter — every external
  exit is sanitized.
* Sampling is trace-level head sampling (deterministic per ``trace_id``), so
  P0/P1 provider switches and local correlation are unaffected.

Supported exporters (see ``configure_export`` / env parsing): ``otlp``
(OTLP/HTTP JSON trace export, OpenTelemetry-compatible) and ``metrics_summary``
(periodic MetricsSnapshot summaries written to local JSONL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import threading
from typing import Any, Protocol

from .metrics import MetricsSnapshot, get_metrics, increment
from .redact import sanitize_attrs
from .span import Span

logger = logging.getLogger(__name__)

__all__ = [
    "ExportConfig",
    "TelemetryExporter",
    "TraceSampler",
    "configure_export",
    "dispatch_span",
    "flush_metrics",
    "flush_span_batches",
    "get_exporters",
    "parse_export_config",
    "register_exporter",
    "set_sampling_ratio",
    "shutdown_exporters",
    "unregister_all",
]

#: Default OTLP/HTTP endpoint (OpenTelemetry Collector default; Phoenix uses
#: ``http://localhost:6006/v1/traces``).
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"

#: Default maximum spans buffered before a synchronous OTLP flush is forced.
DEFAULT_OTLP_BATCH_SIZE = 64

#: Default per-request network timeout for exporters (seconds).
DEFAULT_EXPORT_TIMEOUT_SECONDS = 3.0

#: Default interval between periodic metrics summaries (seconds).
DEFAULT_METRICS_INTERVAL_SECONDS = 60.0


class TelemetryExporter(Protocol):
    """A pluggable sink for telemetry leaving the local process.

    Implementations must be best-effort: methods never raise into the
    producer. ``export_span`` / ``export_metrics`` return ``False`` on
    failure (callers count ``export.<name>.errors``); ``flush`` drains any
    buffered records; ``shutdown`` releases resources.
    """

    def export_span(self, span: Span) -> bool:  # pragma: no cover - protocol
        ...

    def export_metrics(self, snapshot: MetricsSnapshot) -> bool:  # pragma: no cover
        ...

    def flush(self) -> bool:  # pragma: no cover
        ...

    def shutdown(self) -> None:  # pragma: no cover
        ...


# ── registry ───────────────────────────────────────────────────────────────

_EXPORTERS: dict[str, TelemetryExporter] = {}


def register_exporter(name: str, exporter: TelemetryExporter) -> None:
    """Register a named exporter (replaces any previous one with the same name)."""
    _EXPORTERS[name] = exporter


def get_exporters() -> list[tuple[str, TelemetryExporter]]:
    """Return ``(name, exporter)`` pairs in registration order."""
    return list(_EXPORTERS.items())


def unregister_all() -> None:
    """Drop every exporter (tests / teardown). Does not call ``shutdown``."""
    _EXPORTERS.clear()


def shutdown_exporters() -> None:
    """Stop background flushing, then flush + shutdown + drop every exporter.

    Safe to call multiple times and with an empty registry.
    """
    _stop_flusher()
    for name, exporter in list(_EXPORTERS.items()):
        try:
            exporter.shutdown()
        except Exception:  # pragma: no cover - exporters must never break teardown
            logger.debug("exporter %s shutdown failed", name, exc_info=True)
    _EXPORTERS.clear()


# ── sampling ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceSampler:
    """Deterministic trace-level head sampler.

    ``keep(trace_id)`` is stable for a given id, so a trace is either fully
    exported or fully dropped regardless of how many spans it has.
    """

    ratio: float = 1.0

    def keep(self, trace_id: str | None) -> bool:
        if self.ratio >= 1.0:
            return True
        if self.ratio <= 0.0:
            return False
        if not trace_id:
            return True
        # First 8 hex chars = 32 bits, mapped onto [0, 1). Deterministic and
        # free of float-precision loss for full 128-bit trace ids.
        bucket = int(trace_id[:8], 16) / 0xFFFFFFFF
        return bucket < self.ratio


_sampler = TraceSampler(1.0)


def set_sampling_ratio(ratio: float) -> None:
    """Replace the process-wide sampler (used by tests and configuration)."""
    global _sampler
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = 1.0
    _sampler = TraceSampler(max(0.0, min(1.0, ratio)))


# ── dispatch / flush (single exit points) ─────────────────────────────────


def dispatch_span(span: Span) -> None:
    """Fan a finished span out to every registered exporter.

    Applies trace sampling and re-runs redaction before handing the span out,
    so no external exporter can ever observe raw secrets. Never raises.
    """
    if not _EXPORTERS:
        return
    if not _sampler.keep(span.trace_id):
        return
    enriched = _enrich_span(span)
    for name, exporter in list(_EXPORTERS.items()):
        try:
            ok = exporter.export_span(enriched)
        except Exception:  # exporter must never break the producer
            ok = False
        if not ok:
            increment(f"export.{name}.errors")


def flush_metrics() -> None:
    """Snapshot current metrics and fan the summary out to every exporter.

    The metrics summary exporters (local JSONL) rely on this as their stable
    periodic output mechanism. Never raises.
    """
    if not _EXPORTERS:
        return
    snapshot = get_metrics().snapshot()
    for name, exporter in list(_EXPORTERS.items()):
        try:
            ok = exporter.export_metrics(snapshot)
        except Exception:
            ok = False
        if not ok:
            increment(f"export.{name}.errors")


def flush_span_batches() -> None:
    """Ask every exporter to drain any buffered span batches. Never raises."""
    for name, exporter in list(_EXPORTERS.items()):
        try:
            ok = exporter.flush()
        except Exception:
            ok = False
        if not ok:
            increment(f"export.{name}.errors")


def _enrich_span(span: Span) -> Span:
    """Return a copy of *span* carrying stable correlation attributes.

    The original span is never mutated (the local backend already recorded
    it). Correlation ids are added so external backends can trace a span back
    to the Lumen turn / call / request.
    """
    attrs = dict(span.attrs)
    attrs.setdefault("lumen.trace_id", span.trace_id)
    attrs.setdefault("lumen.span.kind", span.kind)
    if span.call_id:
        attrs.setdefault("lumen.call_id", span.call_id)
    return _replace_span(span, attrs)


def _replace_span(span: Span, attrs: dict[str, Any]) -> Span:
    from dataclasses import replace

    return replace(span, attrs=sanitize_attrs(attrs))


# ── background periodic flusher ────────────────────────────────────────────

_flusher_thread: threading.Thread | None = None
_flusher_stop: threading.Event | None = None


def _flusher_loop(interval: float) -> None:
    assert _flusher_stop is not None
    while not _flusher_stop.wait(interval):
        try:
            flush_span_batches()
        except Exception:  # pragma: no cover - loop must keep ticking
            pass
        try:
            flush_metrics()
        except Exception:  # pragma: no cover
            pass


def _start_flusher(interval: float) -> None:
    global _flusher_thread, _flusher_stop
    _stop_flusher()
    _flusher_stop = threading.Event()
    thread = threading.Thread(
        target=_flusher_loop,
        args=(max(1.0, float(interval)),),
        daemon=True,
        name="lumen-telemetry-exporter",
    )
    _flusher_thread = thread
    thread.start()


def _stop_flusher() -> None:
    global _flusher_thread, _flusher_stop
    if _flusher_thread is not None:
        assert _flusher_stop is not None
        _flusher_stop.set()
        _flusher_thread.join(timeout=2.0)
    _flusher_thread = None
    _flusher_stop = None


# ── configuration ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportConfig:
    """Parsed, validated exporter configuration (all optional / local-first)."""

    otlp_enabled: bool = False
    otlp_endpoint: str = DEFAULT_OTLP_ENDPOINT
    otlp_headers: dict[str, str] = field(default_factory=dict)
    otlp_batch_size: int = DEFAULT_OTLP_BATCH_SIZE
    otlp_timeout_seconds: float = DEFAULT_EXPORT_TIMEOUT_SECONDS
    #: Wire encoding for the OTLP/HTTP trace export — ``"json"`` (default,
    #: zero-dependency) or ``"protobuf"`` (required by Phoenix / the OTel
    #: Collector's default OTLP/HTTP receiver).
    otlp_encoding: str = "json"
    metrics_summary_enabled: bool = False
    metrics_summary_dir: str | None = None
    metrics_interval_seconds: float = DEFAULT_METRICS_INTERVAL_SECONDS
    sampling_ratio: float = 1.0
    #: 0 disables the background flusher (spans/metrics are flushed on batch
    #: size, explicit ``flush_*`` calls, and shutdown).
    background_flush_seconds: float = 0.0


def _env(env: dict[str, str] | None, key: str) -> str | None:
    return (env if env is not None else os.environ).get(key)


def parse_export_config(env: dict[str, str] | None = None) -> ExportConfig:
    """Build :class:`ExportConfig` from environment variables.

    Recognized variables (all optional; empty/absent keeps exporters off):

    * ``LUMEN_TELEMETRY_EXPORTERS`` — comma list: ``otlp`` / ``metrics_summary``
    * ``LUMEN_OTEL_ENDPOINT`` — OTLP/HTTP endpoint (default ``:4318/v1/traces``)
    * ``LUMEN_OTEL_ENCODING`` — OTLP/HTTP wire encoding: ``json`` (default)
      or ``protobuf`` (required by Phoenix / the Collector's default receiver)
    * ``LUMEN_OTEL_HEADERS`` — JSON object of extra HTTP headers
    * ``LUMEN_OTEL_BATCH_SIZE`` — spans buffered before a flush
    * ``LUMEN_TELEMETRY_EXPORT_TIMEOUT_SECONDS`` — per-request timeout
    * ``LUMEN_METRICS_EXPORT_INTERVAL_SECONDS`` — periodic metrics interval
    * ``LUMEN_METRICS_SUMMARY_DIR`` — local metrics summary directory
    * ``LUMEN_TELEMETRY_SAMPLING_RATIO`` — 0..1 trace head-sampling ratio
    * ``LUMEN_TELEMETRY_BACKGROUND_FLUSH_SECONDS`` — 0 disables the flusher
    """
    enabled = {
        part.strip()
        for part in (_env(env, "LUMEN_TELEMETRY_EXPORTERS") or "").split(",")
        if part.strip()
    }

    def _float(key: str, default: float) -> float:
        raw = _env(env, key)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _int(key: str, default: int) -> int:
        raw = _env(env, key)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    headers: dict[str, str] = {}
    raw_headers = _env(env, "LUMEN_OTEL_HEADERS")
    if raw_headers:
        try:
            parsed = json.loads(raw_headers)
            if isinstance(parsed, dict):
                headers = {str(k): str(v) for k, v in parsed.items()}
        except (ValueError, TypeError):
            logger.warning("LUMEN_OTEL_HEADERS is not valid JSON; ignoring")

    encoding = (_env(env, "LUMEN_OTEL_ENCODING") or "json").strip().lower()
    if encoding not in {"json", "protobuf"}:
        encoding = "json"

    return ExportConfig(
        otlp_enabled="otlp" in enabled,
        otlp_endpoint=_env(env, "LUMEN_OTEL_ENDPOINT") or DEFAULT_OTLP_ENDPOINT,
        otlp_headers=headers,
        otlp_batch_size=max(1, _int("LUMEN_OTEL_BATCH_SIZE", DEFAULT_OTLP_BATCH_SIZE)),
        otlp_encoding=encoding,
        otlp_timeout_seconds=max(
            0.1, _float("LUMEN_TELEMETRY_EXPORT_TIMEOUT_SECONDS", DEFAULT_EXPORT_TIMEOUT_SECONDS)
        ),
        metrics_summary_enabled="metrics_summary" in enabled,
        metrics_summary_dir=_env(env, "LUMEN_METRICS_SUMMARY_DIR"),
        metrics_interval_seconds=max(
            1.0,
            _float("LUMEN_METRICS_EXPORT_INTERVAL_SECONDS", DEFAULT_METRICS_INTERVAL_SECONDS),
        ),
        sampling_ratio=max(0.0, min(1.0, _float("LUMEN_TELEMETRY_SAMPLING_RATIO", 1.0))),
        background_flush_seconds=max(
            0.0, _float("LUMEN_TELEMETRY_BACKGROUND_FLUSH_SECONDS", 0.0)
        ),
    )


def configure_export(config: ExportConfig | None = None) -> None:
    """Install exporters from *config* (or the environment when unset).

    Local-first: with no enabled exporter this tears down any previous
    registry and leaves the pipeline exactly as Candidates 1 & 2. When
    exporters are enabled and ``background_flush_seconds > 0`` a daemon
    thread periodically drains span batches and flushes metrics summaries.
    """
    cfg = config or parse_export_config()
    shutdown_exporters()
    set_sampling_ratio(cfg.sampling_ratio)

    if cfg.otlp_enabled:
        from .otlp import OtlpSpanExporter

        register_exporter(
            "otlp",
            OtlpSpanExporter(
                endpoint=cfg.otlp_endpoint,
                headers=cfg.otlp_headers,
                batch_size=cfg.otlp_batch_size,
                timeout_seconds=cfg.otlp_timeout_seconds,
                encoding=cfg.otlp_encoding,
            ),
        )
        logger.info("telemetry exporter 'otlp' -> %s (encoding=%s)", cfg.otlp_endpoint, cfg.otlp_encoding)

    if cfg.metrics_summary_enabled:
        from .metrics_export import MetricsSummaryExporter

        register_exporter(
            "metrics_summary",
            MetricsSummaryExporter(out_dir=cfg.metrics_summary_dir),
        )
        logger.info(
            "telemetry exporter 'metrics_summary' -> %s",
            cfg.metrics_summary_dir or "<logs>/telemetry/metrics",
        )

    if _EXPORTERS and cfg.background_flush_seconds > 0:
        _start_flusher(cfg.background_flush_seconds)

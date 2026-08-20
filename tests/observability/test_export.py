"""Candidate 3 export tests — registry, sampling, dispatch, failure isolation.

Verifies the pluggable exporter layer: spans are fanned out to every
registered exporter after the local backend, sampling is trace-level and
deterministic, a failing exporter never breaks the producer or its siblings,
metrics summaries are flushed, and redaction runs before every external exit.
"""

from __future__ import annotations

import time

import pytest

from lumen.shared._util.observability import (
    ExportConfig,
    NoopBackend,
    begin_span,
    finish_span,
    flush_metrics,
    flush_span_batches,
    get_exporters,
    get_metrics,
    increment,
    new_trace_id,
    observe,
    register_exporter,
    reset_metrics,
    set_backend,
    set_sampling_ratio,
    shutdown_exporters,
    unregister_all,
)
from lumen.shared._util.observability.exporter import TraceSampler


class _FakeExporter:
    """Records what the dispatcher hands it; fully isolated."""

    def __init__(self) -> None:
        self.spans: list = []
        self.snapshots: list = []
        self.flush_calls = 0
        self.shutdown_calls = 0
        self.fail_spans = False
        self.fail_metrics = False
        self.fail_flush = False

    def export_span(self, span) -> bool:
        if self.fail_spans:
            raise RuntimeError("boom")
        self.spans.append(span)
        return True

    def export_metrics(self, snapshot) -> bool:
        if self.fail_metrics:
            raise RuntimeError("boom")
        self.snapshots.append(snapshot)
        return True

    def flush(self) -> bool:
        if self.fail_flush:
            return False
        self.flush_calls += 1
        return True

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture(autouse=True)
def _clean_export():
    shutdown_exporters()
    set_backend(NoopBackend())
    reset_metrics()
    set_sampling_ratio(1.0)
    yield
    shutdown_exporters()
    set_backend(NoopBackend())
    reset_metrics()
    set_sampling_ratio(1.0)


def _finish_turn_span(bind: dict | None = None):
    span, token = begin_span("turn", kind="turn", trace_id=new_trace_id(), bind=bind)
    finish_span(span, token)
    return span


# ── registry / dispatch ────────────────────────────────────────────────────


def test_dispatch_is_noop_without_exporters():
    _finish_turn_span({"turn_id": "t1"})
    snap = get_metrics().snapshot()
    assert not snap.counters  # no exporter activity at all


def test_dispatch_fans_out_to_registered_exporters():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    span = _finish_turn_span({"turn_id": "t1", "session_id": "s1"})
    assert len(fake.spans) == 1
    exported = fake.spans[0]
    assert exported.trace_id == span.trace_id
    # Correlation fields are attached to the exported span (not just log ctx).
    assert exported.attrs["turn_id"] == "t1"
    assert exported.attrs["session_id"] == "s1"
    assert exported.attrs["lumen.trace_id"] == span.trace_id
    assert exported.attrs["lumen.span.kind"] == "turn"


def test_failing_exporter_is_isolated_and_counted():
    good = _FakeExporter()
    bad = _FakeExporter()
    bad.fail_spans = True
    register_exporter("good", good)
    register_exporter("bad", bad)
    _finish_turn_span()  # must not raise
    assert len(good.spans) == 1  # sibling still receives the span
    snap = get_metrics().snapshot()
    assert snap.counters.get("export.bad.errors", 0) >= 1


def test_registry_shutdown_flushes_and_clears():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    shutdown_exporters()
    assert fake.shutdown_calls == 1
    assert get_exporters() == []


# ── sampling ───────────────────────────────────────────────────────────────


def test_sampler_ratio_boundaries():
    import hashlib

    assert TraceSampler(1.0).keep("a" * 32) is True
    assert TraceSampler(0.0).keep("a" * 32) is False
    s = TraceSampler(0.5)
    # deterministic: same id, same decision
    assert s.keep("a" * 32) == s.keep("a" * 32)
    # both halves populated across a sample of well-spread ids
    def _trace(i: int) -> str:
        return hashlib.sha1(f"{i}".encode()).hexdigest()[:32]

    kept = sum(1 for i in range(200) if s.keep(_trace(i)))
    assert 0 < kept < 200


def test_sampling_ratio_zero_drops_all_exports():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    set_sampling_ratio(0.0)
    _finish_turn_span()
    assert fake.spans == []


def test_sampling_ratio_one_exports_all():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    _finish_turn_span()
    _finish_turn_span()
    assert len(fake.spans) == 2


# ── metrics flush ──────────────────────────────────────────────────────────


def test_flush_metrics_fans_snapshot_to_exporters():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    increment("turn.completed")
    observe("turn.duration", 0.5)
    flush_metrics()
    assert len(fake.snapshots) == 1
    assert fake.snapshots[0].counters["turn.completed"] >= 1
    assert "turn.duration" in fake.snapshots[0].histograms


def test_failing_metrics_exporter_is_isolated():
    bad = _FakeExporter()
    bad.fail_metrics = True
    register_exporter("bad", bad)
    increment("turn.completed")
    flush_metrics()  # must not raise
    snap = get_metrics().snapshot()
    assert snap.counters.get("export.bad.errors", 0) >= 1


def test_flush_span_batches_calls_flush():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    flush_span_batches()
    assert fake.flush_calls == 1
    # failed flush is counted, not raised
    fake.fail_flush = True
    flush_span_batches()
    snap = get_metrics().snapshot()
    assert snap.counters.get("export.fake.errors", 0) >= 1


# ── redaction at the export boundary ───────────────────────────────────────


def test_dispatch_redacts_before_external_exit():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    span, token = begin_span(
        "turn",
        kind="turn",
        trace_id=new_trace_id(),
        attrs={"api_key": "sk-super-secret", "model": "gpt-4"},
    )
    finish_span(span, token)
    exported = fake.spans[0]
    assert exported.attrs["api_key"] == "[REDACTED]"
    assert exported.attrs["model"] == "gpt-4"


# ── configuration / env ────────────────────────────────────────────────────


def test_parse_export_config_defaults_to_off():
    cfg = ExportConfig()
    assert cfg.otlp_enabled is False
    assert cfg.metrics_summary_enabled is False
    assert cfg.sampling_ratio == 1.0


def test_configure_export_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMEN_TELEMETRY_EXPORTERS", "metrics_summary")
    monkeypatch.setenv("LUMEN_METRICS_SUMMARY_DIR", str(tmp_path))
    monkeypatch.setenv("LUMEN_TELEMETRY_SAMPLING_RATIO", "0.5")
    from lumen.shared._util.observability import parse_export_config

    cfg = parse_export_config()
    assert cfg.metrics_summary_enabled is True
    assert cfg.otlp_enabled is False
    assert cfg.sampling_ratio == 0.5
    assert cfg.metrics_summary_dir == str(tmp_path)


def test_configure_export_registers_exporters(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMEN_TELEMETRY_EXPORTERS", "metrics_summary")
    monkeypatch.setenv("LUMEN_METRICS_SUMMARY_DIR", str(tmp_path))
    from lumen.shared._util.observability import configure_export

    configure_export()
    names = {name for name, _ in get_exporters()}
    assert names == {"metrics_summary"}
    # re-configure with nothing tears the previous registry down
    monkeypatch.delenv("LUMEN_TELEMETRY_EXPORTERS")
    configure_export()
    assert get_exporters() == []


def test_unconfigured_export_is_stable_and_fast():
    """With no exporters, dispatch adds no measurable work and no errors."""
    start = time.monotonic()
    for _ in range(200):
        _finish_turn_span()
    elapsed = time.monotonic() - start
    snap = get_metrics().snapshot()
    assert elapsed < 5.0  # loose sanity bound; the point is zero exporter I/O
    assert not any(k.startswith("export.") for k in snap.counters)


def test_unregister_all_drops_exporters_without_shutdown():
    fake = _FakeExporter()
    register_exporter("fake", fake)
    unregister_all()
    assert fake.shutdown_calls == 0
    assert get_exporters() == []

"""Candidate 3 metrics export tests — periodic summary output mechanism.

Verifies :class:`MetricsSummaryExporter` writes stable local JSONL summaries
and that :func:`flush_metrics` (the periodic orchestration entry point)
delivers snapshots to registered exporters.
"""

from __future__ import annotations

import json
import time

import pytest

from lumen.shared._util.observability import (
    NoopBackend,
    flush_metrics,
    get_metrics,
    increment,
    observe,
    register_exporter,
    reset_metrics,
    set_backend,
    shutdown_exporters,
)
from lumen.shared._util.observability.metrics_export import MetricsSummaryExporter


@pytest.fixture(autouse=True)
def _clean():
    shutdown_exporters()
    set_backend(NoopBackend())
    reset_metrics()
    yield
    shutdown_exporters()
    set_backend(NoopBackend())
    reset_metrics()


def test_summary_exporter_writes_jsonl_snapshot(tmp_path):
    exporter = MetricsSummaryExporter(out_dir=tmp_path)
    increment("turn.completed")
    observe("turn.duration", 0.5)
    assert exporter.export_metrics(get_metrics().snapshot()) is True

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    line = json.loads(files[0].read_text(encoding="utf-8"))
    assert line["counters"]["turn.completed"] >= 1
    assert "turn.duration" in line["histograms"]


def test_flush_metrics_writes_periodic_summary(tmp_path):
    register_exporter("metrics_summary", MetricsSummaryExporter(out_dir=tmp_path))
    increment("llm.total")
    flush_metrics()
    flush_metrics()  # periodic flushes accumulate lines, not overwrite
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_summary_exporter_ignores_spans(tmp_path):
    exporter = MetricsSummaryExporter(out_dir=tmp_path)
    assert exporter.export_span(None) is True
    assert list(tmp_path.glob("*.jsonl")) == []


def test_summary_exporter_prunes_stale_files(tmp_path):
    """Metrics summaries older than the retention window are pruned once/day,
    so the local metrics output stays bounded (documented 7-day lifecycle)."""
    import os
    import time as _time

    exporter = MetricsSummaryExporter(out_dir=tmp_path, retention_days=7)
    stale = tmp_path / "old-stale.jsonl"
    stale.write_text("old")
    old = _time.time() - 8 * 86400
    os.utime(stale, (old, old))
    # a fresh file is also present and must survive
    fresh = tmp_path / "keep.jsonl"
    fresh.write_text("new")

    assert exporter.export_metrics(get_metrics().snapshot()) is True
    assert not stale.exists(), "stale metrics summary should be pruned"
    assert fresh.exists(), "fresh file must survive pruning"
    assert (
        exporter.export_metrics(get_metrics().snapshot()) is True
    )  # idempotent, no re-prune error


def test_background_flusher_ticks(tmp_path):
    """Periodic flusher drains span batches + metrics summaries on schedule."""
    from lumen.shared._util.observability import ExportConfig, configure_export
    from lumen.shared._util.observability.exporter import _stop_flusher

    cfg = ExportConfig(
        metrics_summary_enabled=True,
        metrics_summary_dir=str(tmp_path),
        background_flush_seconds=0.05,
    )
    try:
        configure_export(cfg)
        increment("turn.completed")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            files = list(tmp_path.glob("*.jsonl"))
            if files:
                break
            time.sleep(0.05)
        else:
            pytest.fail("background flusher never wrote a metrics summary")
    finally:
        _stop_flusher()
        shutdown_exporters()


def test_config_env_activates_periodic_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMEN_TELEMETRY_EXPORTERS", "metrics_summary")
    monkeypatch.setenv("LUMEN_METRICS_SUMMARY_DIR", str(tmp_path))
    from lumen.shared._util.observability import configure_export

    configure_export()
    increment("turn.failed")
    flush_metrics()
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    line = json.loads(files[0].read_text(encoding="utf-8"))
    assert line["counters"]["turn.failed"] >= 1

"""Stable periodic metrics output (Candidate 3).

The process-wide :class:`MetricsRecorder` aggregates counters and histograms
in memory. :func:`flush_metrics` (in ``exporter.py``) snapshots it and fans the
summary out to every registered exporter; :class:`MetricsSummaryExporter`
persists each summary to a local JSONL file under
``<logs>/telemetry/metrics/``. Together they give Metrics a stable periodic
output / export mechanism without coupling the business layer to any backend.

The summary file contains only aggregated numbers (no user content, no raw
spans), so it is safe to keep next to the local span JSONL backend.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any

from .exporter import TelemetryExporter
from .metrics import MetricsSnapshot

__all__ = ["MetricsSummaryExporter"]


class MetricsSummaryExporter(TelemetryExporter):
    """Append periodic :class:`MetricsSnapshot` summaries to JSONL files.

    One line per flush, keyed by date file: ``metrics-YYYY-MM-DD.jsonl``.
    ``out_dir`` defaults to the path service logs directory (``telemetry/
    metrics``). All I/O is best-effort — failures return ``False`` and are
    counted by the dispatcher, never raised into the producer.
    """

    def __init__(self, out_dir: str | Path | None = None) -> None:
        self._out_dir: str | Path | None = out_dir
        self._lock = threading.Lock()

    def _resolve_dir(self) -> Path | None:
        if self._out_dir is not None:
            return Path(self._out_dir)
        try:
            from lumen.shared._util.path_service import get_path_service

            return get_path_service().get_logs_dir() / "telemetry" / "metrics"
        except Exception:  # pragma: no cover - environment dependent
            return None

    def export_metrics(self, snapshot: MetricsSnapshot) -> bool:
        base = self._resolve_dir()
        if base is None:
            return False
        try:
            base.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "counters": snapshot.counters,
                "histograms": snapshot.histograms,
            }
            line = json.dumps(payload, ensure_ascii=False, default=str)
            path = base / f"{date.today().isoformat()}.jsonl"
            with self._lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.write("\n")
            return True
        except Exception:  # pragma: no cover - summary must never break the producer
            return False

    def export_span(self, span: Any) -> bool:
        # The summary exporter only consumes metrics snapshots.
        return True

    def flush(self) -> bool:
        return True

    def shutdown(self) -> None:
        return None

"""In-process metrics aggregation (counters + histograms).

Round 1 keeps aggregation in memory: counters and a bounded histogram
buffer per metric name. ``snapshot()`` returns plain dicts so the local
backend / a future periodic summary can flush them. Metric recording must
never break the producer — all failures are swallowed.
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ["MetricsRecorder", "MetricsSnapshot"]

_HISTOGRAM_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)


class MetricsSnapshot:
    """Immutable view of aggregated metrics at a point in time."""

    def __init__(self, counters: dict[str, int], histograms: dict[str, dict[str, Any]]) -> None:
        self.counters = dict(counters)
        self.histograms = {k: dict(v) for k, v in histograms.items()}

    def to_dict(self) -> dict[str, Any]:
        return {"counters": self.counters, "histograms": self.histograms}


class MetricsRecorder:
    """Thread-safe counters + bucketed histograms keyed by metric name."""

    def __init__(self, buckets: tuple[float, ...] = _HISTOGRAM_BUCKETS) -> None:
        self._buckets = tuple(sorted(buckets))
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, list[float]] = {}

    def increment(self, name: str, value: int = 1) -> None:
        """Increment a named counter (value defaults to 1)."""
        if value == 0:
            return
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def observe(self, name: str, value: float) -> None:
        """Record one sample into a named histogram (seconds, counts, …)."""
        try:
            sample = float(value)
        except (TypeError, ValueError):
            return
        if sample < 0:
            return
        with self._lock:
            series = self._histograms.get(name)
            if series is None:
                series = []
                self._histograms[name] = series
            series.append(sample)

    def snapshot(self) -> MetricsSnapshot:
        """Return an immutable snapshot of current counters and histograms."""
        with self._lock:
            hist = {}
            for name, series in self._histograms.items():
                hist[name] = self._summarize(series)
            return MetricsSnapshot(dict(self._counters), hist)

    def _summarize(self, series: list[float]) -> dict[str, Any]:
        if not series:
            return {"count": 0, "sum": 0.0}
        total = sum(series)
        count = len(series)
        mean = total / count
        sorted_series = sorted(series)
        def percentile(p: float) -> float:
            if not sorted_series:
                return 0.0
            idx = min(len(sorted_series) - 1, int(p * len(sorted_series)))
            return sorted_series[idx]
        return {
            "count": count,
            "sum": total,
            "mean": mean,
            "p50": percentile(0.5),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": sorted_series[-1],
        }

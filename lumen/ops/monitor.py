"""Production Operations — unified health / service-level monitor.

Combines the SLI/SLO evaluation (``sli``), the capacity & lifecycle report
(``capacity``) and live probes (persistence / telemetry writability) into one
canonical :func:`build_health_report`. This is the report served by the
detailed health endpoint (``GET /api/v1/health/detailed``) and consumed by the
``lumenctl sli`` / ``lumenctl health --detailed`` ops tooling.

The monitor is intentionally stateless and pure: callers own the process
metrics snapshot, the live SQLite probe result and the path service, so it
stays trivially testable and never performs its own I/O beyond the read-only
capacity walk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from lumen.shared._util.observability import MetricsSnapshot, get_metrics

from .capacity import DEFAULT_SOFT_MAX_BYTES, LogRetention, capacity_report, retention_status
from .sli import (
    SLI_STATUS_CRITICAL,
    SLI_STATUS_OK,
    SLI_STATUS_WARN,
    SLOConfig,
    evaluate_all,
    load_slo_config,
    overall_is_healthy,
)

__all__ = [
    "build_health_report",
    "telemetry_health",
    "overall_status",
]

PersistenceProbe = Callable[[], bool]


def _fresh(entry: dict[str, Any]) -> bool:
    return bool(entry.get("fresh", True))


def telemetry_health(logs_dir: Any) -> dict[str, Any]:
    """Live writability/freshness of the local telemetry pipeline.

    ``logs_dir`` is the path service logs directory. A missing or empty
    telemetry dir is not an error (no traffic yet / local backend disabled);
    a dir that stopped producing (all files older than the retention window)
    is reported unhealthy so operators notice a silently-dead pipeline.
    """
    status = retention_status(logs_dir, retention=LogRetention())
    telemetry = status.get("telemetry", {})
    healthy = True
    reason = "no_telemetry_files"
    if telemetry.get("files"):
        healthy = _fresh(telemetry)
        reason = "fresh" if healthy else "stale"
    return {
        "ok": bool(healthy),
        "reason": reason,
        "files": telemetry.get("files", 0),
        "newest_mtime": telemetry.get("newest_mtime", 0),
        "window_days": telemetry.get("window_days", 0),
    }


def overall_status(
    sli_report: dict[str, Any],
    *,
    telemetry_ok: bool,
    capacity_ok: bool,
) -> str:
    """Roll up the overall operational status (ok / warn / critical)."""
    sli_status = sli_report.get("status", SLI_STATUS_CRITICAL)
    if sli_status == SLI_STATUS_CRITICAL or not telemetry_ok or not capacity_ok:
        return SLI_STATUS_CRITICAL
    if sli_status == SLI_STATUS_WARN:
        return SLI_STATUS_WARN
    return SLI_STATUS_OK


def build_health_report(
    *,
    snapshot: MetricsSnapshot | None = None,
    persistence_ok: bool = True,
    slo: SLOConfig | None = None,
    path_service: Any | None = None,
    soft_max_bytes: int = DEFAULT_SOFT_MAX_BYTES,
    telemetry_probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the canonical Production Operations health report.

    Args:
        snapshot: process metrics snapshot (defaults to the live recorder).
        persistence_ok: result of the live storage probe (SQLite ping).
        slo: SLO thresholds (defaults to environment configuration).
        path_service: active path service (capacity report source).
        soft_max_bytes: soft capacity boundary for the data tree.
        telemetry_probe: returns the ``telemetry_health`` dict (injectable
            for tests; defaults to the local logs dir probe).
    """
    slo = slo or load_slo_config()
    snapshot = snapshot if snapshot is not None else get_metrics().snapshot()

    if telemetry_probe is not None:
        telemetry = telemetry_probe()
    else:
        logs_dir = None
        if path_service is not None:
            try:
                logs_dir = path_service.get_logs_dir()
            except Exception:  # pragma: no cover - environment dependent
                logs_dir = None
        telemetry = (
            telemetry_health(logs_dir)
            if logs_dir is not None
            else {"ok": True, "reason": "no_logs_dir"}
        )

    sli_report = evaluate_all(
        snapshot, slo, persistence_ok=persistence_ok, telemetry_ok=telemetry["ok"]
    )

    capacity: dict[str, Any] = {}
    if path_service is not None:
        try:
            capacity = capacity_report(path_service, soft_max_bytes=soft_max_bytes)
        except Exception:  # pragma: no cover - capacity must never break health
            capacity = {"within_capacity": True, "error": "capacity_report_failed"}

    capacity_ok = bool(capacity.get("within_capacity", True))

    return {
        "status": overall_status(sli_report, telemetry_ok=telemetry["ok"], capacity_ok=capacity_ok),
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "sli": sli_report,
        "telemetry": telemetry,
        "capacity": capacity,
        "healthy": bool(overall_is_healthy(sli_report) and telemetry["ok"] and capacity_ok),
    }

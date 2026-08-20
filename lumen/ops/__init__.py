"""Lumen Production Operations — SLI/SLO monitoring, capacity & lifecycle.

A read-only ops layer built on top of the frozen observability core. It turns
the process metrics (counters + histograms), the live persistence probe and
the data layout into service-level indicators / objectives (SLI/SLO), a
capacity & retention report, and a unified health report for operators.

Ownership rules mirror the Architecture Gates: this package depends only on
private shared utilities (``lumen.shared._util.observability`` /
``lumen.shared._util.path_service``) plus a caller-injected path service and
persistence probe. It never imports runtime providers or modes, so it cannot
create a forbidden dependency edge.
"""

from .capacity import LogRetention, capacity_report, dir_size, retention_status, walk_sizes
from .monitor import build_health_report, overall_status, telemetry_health
from .sli import (
    SLI_STATUS_CRITICAL,
    SLI_STATUS_OK,
    SLI_STATUS_WARN,
    SLOConfig,
    compute_sli,
    evaluate_all,
    evaluate_persistence,
    evaluate_sli,
    load_slo_config,
    overall_is_healthy,
)

__all__ = [
    # sli
    "SLOConfig",
    "load_slo_config",
    "compute_sli",
    "evaluate_sli",
    "evaluate_persistence",
    "evaluate_all",
    "overall_is_healthy",
    "SLI_STATUS_OK",
    "SLI_STATUS_WARN",
    "SLI_STATUS_CRITICAL",
    # capacity
    "LogRetention",
    "capacity_report",
    "dir_size",
    "retention_status",
    "walk_sizes",
    # monitor
    "build_health_report",
    "overall_status",
    "telemetry_health",
]

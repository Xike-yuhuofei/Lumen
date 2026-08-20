"""Production Operations — SLI / SLO definitions, computation and evaluation.

The Production Operations layer sits above the frozen observability core
(``lumen.shared._util.observability``) and turns its raw signals (counters +
histograms, live persistence probe, telemetry health) into service-level
indicators with service-level objectives:

* **SLI** — a measurable ratio/latency derived from the process metrics that
  maps onto a core-link availability property (Turn / LLM / Tool / Retrieval /
  Persistence / Telemetry).
* **SLO** — the target threshold for each SLI, expressed as ``error_budget`` /
  ``p95_budget_s``. Thresholds are configurable via ``LUMEN_SLO_*`` env vars
  so operators can tune them without code changes.
* **Evaluation** — each SLI yields ``ok`` / ``warn`` / ``critical``; the
  overall SLO status is the worst of all SLIs. No user content, no secrets:
  only aggregated counters and rates.

This module never performs I/O itself; callers (the detailed health endpoint,
``lumenctl``, the periodic monitor) pass in the inputs they already own.
"""

from __future__ import annotations

import os
from typing import Any

from lumen.shared._util.observability import MetricsSnapshot

__all__ = [
    "SLOConfig",
    "load_slo_config",
    "compute_sli",
    "evaluate_sli",
    "evaluate_all",
    "SLI_STATUS_OK",
    "SLI_STATUS_WARN",
    "SLI_STATUS_CRITICAL",
]

SLI_STATUS_OK = "ok"
SLI_STATUS_WARN = "warn"
SLI_STATUS_CRITICAL = "critical"

_SLI_ORDER = ("turn", "llm", "tool", "retrieval", "persistence", "telemetry")


class SLOConfig:
    """Service-level objective thresholds for each SLI.

    All fields are configurable through ``LUMEN_SLO_*`` environment variables
    (see :func:`load_slo_config`); the defaults below are the validated
    production starting point.
    """

    def __init__(
        self,
        *,
        turn_success_min: float = 0.95,
        turn_p95_max_s: float = 30.0,
        llm_error_max: float = 0.05,
        llm_p95_max_s: float = 30.0,
        tool_error_max: float = 0.10,
        retrieval_error_max: float = 0.10,
        telemetry_export_error_max: float = 0.10,
        warn_factor: float = 0.5,
        min_samples: int = 1,
    ) -> None:
        self.turn_success_min = turn_success_min
        self.turn_p95_max_s = turn_p95_max_s
        self.llm_error_max = llm_error_max
        self.llm_p95_max_s = llm_p95_max_s
        self.tool_error_max = tool_error_max
        self.retrieval_error_max = retrieval_error_max
        self.telemetry_export_error_max = telemetry_export_error_max
        # warn fires when an error-rate SLI already exceeded warn_factor of its
        # objective (a soft headroom warning before the hard SLO is breached).
        self.warn_factor = max(0.0, min(1.0, warn_factor))
        self.min_samples = max(0, int(min_samples))

    def _slop(self, threshold: float) -> float:
        """Distance from the objective at which warn starts (fraction)."""
        return (1.0 - self.warn_factor) * threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_success_min": self.turn_success_min,
            "turn_p95_max_s": self.turn_p95_max_s,
            "llm_error_max": self.llm_error_max,
            "llm_p95_max_s": self.llm_p95_max_s,
            "tool_error_max": self.tool_error_max,
            "retrieval_error_max": self.retrieval_error_max,
            "telemetry_export_error_max": self.telemetry_export_error_max,
            "warn_factor": self.warn_factor,
            "min_samples": self.min_samples,
        }


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_slo_config(env: dict[str, str] | None = None) -> SLOConfig:
    """Build an :class:`SLOConfig` from the environment (or *env* for tests).

    Recognized variables (all optional):
    ``LUMEN_SLO_TURN_SUCCESS_MIN``, ``LUMEN_SLO_TURN_P95_MAX_S``,
    ``LUMEN_SLO_LLM_ERROR_MAX``, ``LUMEN_SLO_LLM_P95_MAX_S``,
    ``LUMEN_SLO_TOOL_ERROR_MAX``, ``LUMEN_SLO_RETRIEVAL_ERROR_MAX``,
    ``LUMEN_SLO_TELEMETRY_EXPORT_ERROR_MAX``, ``LUMEN_SLO_WARN_FACTOR``,
    ``LUMEN_SLO_MIN_SAMPLES``.
    """
    source = env if env is not None else os.environ

    def _f(name: str, default: float) -> float:
        raw = source.get(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return SLOConfig(
        turn_success_min=_f("LUMEN_SLO_TURN_SUCCESS_MIN", 0.95),
        turn_p95_max_s=_f("LUMEN_SLO_TURN_P95_MAX_S", 30.0),
        llm_error_max=_f("LUMEN_SLO_LLM_ERROR_MAX", 0.05),
        llm_p95_max_s=_f("LUMEN_SLO_LLM_P95_MAX_S", 30.0),
        tool_error_max=_f("LUMEN_SLO_TOOL_ERROR_MAX", 0.10),
        retrieval_error_max=_f("LUMEN_SLO_RETRIEVAL_ERROR_MAX", 0.10),
        telemetry_export_error_max=_f("LUMEN_SLO_TELEMETRY_EXPORT_ERROR_MAX", 0.10),
        warn_factor=_f("LUMEN_SLO_WARN_FACTOR", 0.5),
        min_samples=int(_f("LUMEN_SLO_MIN_SAMPLES", 1)),
    )


def _rate(errors: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(1.0, errors / total)


def _p95(hist: dict[str, Any] | None) -> float:
    if not hist:
        return 0.0
    try:
        return float(hist.get("p95") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute_sli(snapshot: MetricsSnapshot) -> dict[str, Any]:
    """Compute every SLI from a metrics snapshot.

    Returns a dict keyed by SLI name with the raw measurements needed for
    evaluation and reporting: ``total`` / ``errors`` / ``success_rate`` /
    ``error_rate`` / ``p95_s``. Only counts that have occurred appear; an
    absent SLI means "no traffic yet" and is reported as ``ok`` (no samples).
    """
    counters = snapshot.counters
    histograms = snapshot.histograms

    turn_total = sum(
        counters.get(f"turn.{outcome}", 0) for outcome in ("completed", "failed", "cancelled")
    )
    turn_failed = counters.get("turn.failed", 0)
    turn_cancelled = counters.get("turn.cancelled", 0)

    out: dict[str, Any] = {
        "turn": {
            "total": turn_total,
            "failed": turn_failed,
            "cancelled": turn_cancelled,
            "success_rate": 1.0 - _rate(turn_failed + turn_cancelled, turn_total),
            "p95_s": _p95(histograms.get("turn.duration")),
        },
        "llm": {
            "total": counters.get("llm.total", 0),
            "errors": counters.get("llm.errors", 0),
            "retries": counters.get("llm.retries", 0),
            "error_rate": _rate(counters.get("llm.errors", 0), counters.get("llm.total", 0)),
            "p95_s": _p95(histograms.get("llm.latency")),
        },
        "tool": {
            "total": counters.get("tool.total", 0),
            "errors": counters.get("tool.errors", 0),
            "error_rate": _rate(counters.get("tool.errors", 0), counters.get("tool.total", 0)),
            "p95_s": _p95(histograms.get("tool.latency")),
        },
        "retrieval": {
            "total": counters.get("retrieval.total", 0),
            "errors": counters.get("retrieval.errors", 0),
            "error_rate": _rate(
                counters.get("retrieval.errors", 0), counters.get("retrieval.total", 0)
            ),
        },
    }

    # Telemetry SLI aggregates every registered external exporter: a single
    # failing export path is reported, an absent exporter is a no-op.
    telemetry_total = 0
    telemetry_errors = 0
    for name, errors in counters.items():
        if name.startswith("export.") and name.endswith(".errors"):
            total_name = f"export.{name[len('export.') : -len('.errors')]}.total"
            telemetry_total += counters.get(total_name, errors)
            telemetry_errors += errors
    out["telemetry"] = {
        "export_errors": telemetry_errors,
        "error_rate": _rate(telemetry_errors, telemetry_total),
    }

    return out


def _status_for_error_rate(error_rate: float, threshold: float, warn_at: float) -> str:
    if error_rate <= warn_at:
        return SLI_STATUS_OK
    if error_rate <= threshold:
        return SLI_STATUS_WARN
    return SLI_STATUS_CRITICAL


def evaluate_sli(name: str, sli: dict[str, Any], slo: SLOConfig) -> dict[str, Any]:
    """Evaluate one computed SLI against the SLO and attach a status.

    ``sli`` is a single entry from :func:`compute_sli`. Returns a copy with
    ``status`` and ``slo`` (the threshold used) added. Persistence is handled
    by :func:`evaluate_persistence`.
    """
    result = dict(sli)
    if name == "turn":
        total = sli.get("total", 0)
        if total < slo.min_samples:
            result["status"] = SLI_STATUS_OK
            result["slo"] = None
            return result
        success = sli.get("success_rate", 1.0)
        warn_at = slo.turn_success_min - (1.0 - slo.warn_factor) * (1.0 - slo.turn_success_min)
        if success >= slo.turn_success_min:
            result["status"] = SLI_STATUS_OK
        elif success >= warn_at:
            result["status"] = SLI_STATUS_WARN
        else:
            result["status"] = SLI_STATUS_CRITICAL
        p95 = sli.get("p95_s", 0.0)
        if result["status"] != SLI_STATUS_CRITICAL and p95 > slo.turn_p95_max_s:
            result["status"] = SLI_STATUS_CRITICAL
        result["slo"] = {
            "success_min": slo.turn_success_min,
            "p95_max_s": slo.turn_p95_max_s,
        }
        return result

    if name == "llm":
        total = sli.get("total", 0)
        if total < slo.min_samples:
            result["status"] = SLI_STATUS_OK
            result["slo"] = None
            return result
        err_rate = sli.get("error_rate", 0.0)
        status = _status_for_error_rate(err_rate, slo.llm_error_max, slo._slop(slo.llm_error_max))
        p95 = sli.get("p95_s", 0.0)
        if status != SLI_STATUS_CRITICAL and p95 > slo.llm_p95_max_s:
            status = SLI_STATUS_CRITICAL
        result["status"] = status
        result["slo"] = {"error_max": slo.llm_error_max, "p95_max_s": slo.llm_p95_max_s}
        return result

    if name == "tool":
        total = sli.get("total", 0)
        if total < slo.min_samples:
            result["status"] = SLI_STATUS_OK
            result["slo"] = None
            return result
        result["status"] = _status_for_error_rate(
            sli.get("error_rate", 0.0), slo.tool_error_max, slo._slop(slo.tool_error_max)
        )
        result["slo"] = {"error_max": slo.tool_error_max}
        return result

    if name == "retrieval":
        total = sli.get("total", 0)
        if total < slo.min_samples:
            result["status"] = SLI_STATUS_OK
            result["slo"] = None
            return result
        result["status"] = _status_for_error_rate(
            sli.get("error_rate", 0.0),
            slo.retrieval_error_max,
            slo._slop(slo.retrieval_error_max),
        )
        result["slo"] = {"error_max": slo.retrieval_error_max}
        return result

    if name == "telemetry":
        errors = sli.get("export_errors", 0)
        if errors == 0:
            result["status"] = SLI_STATUS_OK
            result["slo"] = None
            return result
        result["status"] = _status_for_error_rate(
            sli.get("error_rate", 0.0),
            slo.telemetry_export_error_max,
            slo._slop(slo.telemetry_export_error_max),
        )
        result["slo"] = {"error_max": slo.telemetry_export_error_max}
        return result

    result["status"] = SLI_STATUS_OK
    result["slo"] = None
    return result


def evaluate_persistence(ok: bool) -> dict[str, Any]:
    """Evaluate the persistence SLI from a live storage probe."""
    return {
        "ok": bool(ok),
        "status": SLI_STATUS_OK if ok else SLI_STATUS_CRITICAL,
    }


def evaluate_all(
    snapshot: MetricsSnapshot,
    slo: SLOConfig,
    *,
    persistence_ok: bool = True,
    telemetry_ok: bool = True,
) -> dict[str, Any]:
    """Evaluate every SLI and roll up the overall SLO status.

    ``persistence_ok`` comes from a live storage probe (e.g. the SQLite ping);
    ``telemetry_ok`` reflects whether local span/metrics files are writable
    (checked by the caller). The returned dict is the canonical "service level
    report" consumed by the detailed health endpoint and the ops CLI.
    """
    computed = compute_sli(snapshot)
    slis: dict[str, Any] = {}
    for name in _SLI_ORDER:
        if name == "persistence":
            slis[name] = evaluate_persistence(persistence_ok)
            continue
        if name == "telemetry":
            value = evaluate_sli("telemetry", computed["telemetry"], slo)
            if not telemetry_ok:
                value["status"] = SLI_STATUS_CRITICAL
            slis[name] = value
            continue
        slis[name] = evaluate_sli(name, computed[name], slo)

    if not persistence_ok or not telemetry_ok:
        overall = SLI_STATUS_CRITICAL
    else:
        worst = SLI_STATUS_OK
        for value in slis.values():
            status = value.get("status", SLI_STATUS_OK)
            if _rank(status) > _rank(worst):
                worst = status
        overall = worst

    return {
        "status": overall,
        "slis": slis,
        "slo": slo.to_dict(),
    }


def _rank(status: str) -> int:
    return {SLI_STATUS_OK: 0, SLI_STATUS_WARN: 1, SLI_STATUS_CRITICAL: 2}.get(status, 0)


def overall_is_healthy(report: dict[str, Any]) -> bool:
    """True when the report carries no warn/critical SLI."""
    return report.get("status", SLI_STATUS_CRITICAL) == SLI_STATUS_OK

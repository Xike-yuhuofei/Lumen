"""Production Operations SLI / SLO tests.

Verifies SLI computation from a metrics snapshot, per-SLI evaluation against
SLO thresholds (ok / warn / critical) and the overall roll-up, including the
live persistence / telemetry inputs.
"""

from __future__ import annotations

from lumen.ops.sli import (
    SLI_STATUS_CRITICAL,
    SLI_STATUS_OK,
    SLI_STATUS_WARN,
    SLOConfig,
    compute_sli,
    evaluate_all,
    evaluate_sli,
    load_slo_config,
    overall_is_healthy,
)
from lumen.shared._util.observability import MetricsSnapshot


def _snap(counters: dict[str, int], histograms: dict[str, dict] | None = None) -> MetricsSnapshot:
    return MetricsSnapshot(dict(counters), dict(histograms or {}))


def _p95_hist(p95: float) -> dict[str, float]:
    return {"count": 1, "sum": p95, "mean": p95, "p50": p95, "p95": p95, "p99": p95, "max": p95}


def test_compute_sli_turn_rates() -> None:
    snap = _snap(
        {"turn.completed": 90, "turn.failed": 8, "turn.cancelled": 2},
        {"turn.duration": _p95_hist(2.5)},
    )
    sli = compute_sli(snap)["turn"]
    assert sli["total"] == 100
    assert sli["failed"] == 8
    assert sli["cancelled"] == 2
    assert abs(sli["success_rate"] - 0.90) < 1e-9
    assert sli["p95_s"] == 2.5


def test_compute_sli_llm_tool_retrieval() -> None:
    snap = _snap(
        {
            "llm.total": 100,
            "llm.errors": 3,
            "llm.retries": 2,
            "tool.total": 40,
            "tool.errors": 4,
            "retrieval.total": 10,
            "retrieval.errors": 1,
        },
        {"llm.latency": _p95_hist(1.2), "tool.latency": _p95_hist(0.8)},
    )
    computed = compute_sli(snap)
    assert abs(computed["llm"]["error_rate"] - 0.03) < 1e-9
    assert computed["llm"]["p95_s"] == 1.2
    assert abs(computed["tool"]["error_rate"] - 0.10) < 1e-9
    assert abs(computed["retrieval"]["error_rate"] - 0.10) < 1e-9
    # no telemetry exporters -> no errors
    assert computed["telemetry"]["export_errors"] == 0


def test_compute_sli_telemetry_export_errors() -> None:
    snap = _snap(
        {
            "export.otlp.total": 100,
            "export.otlp.errors": 7,
            "export.metrics_summary.total": 50,
            "export.metrics_summary.errors": 0,
        }
    )
    telemetry = compute_sli(snap)["telemetry"]
    assert telemetry["export_errors"] == 7
    assert abs(telemetry["error_rate"] - 7 / 150) < 1e-9


def test_turn_evaluation_statuses() -> None:
    slo = SLOConfig(turn_success_min=0.95, warn_factor=0.5)
    # ok
    assert (
        evaluate_sli("turn", {"total": 100, "success_rate": 0.98, "p95_s": 5.0}, slo)["status"]
        == SLI_STATUS_OK
    )
    # warn: below success but above the warn floor (0.95 - 0.5*(0.05) = 0.925)
    assert (
        evaluate_sli("turn", {"total": 100, "success_rate": 0.94, "p95_s": 5.0}, slo)["status"]
        == SLI_STATUS_WARN
    )
    # critical: below warn floor
    assert (
        evaluate_sli("turn", {"total": 100, "success_rate": 0.90, "p95_s": 5.0}, slo)["status"]
        == SLI_STATUS_CRITICAL
    )
    # critical on latency even with success ok
    assert (
        evaluate_sli("turn", {"total": 100, "success_rate": 0.98, "p95_s": 60.0}, slo)["status"]
        == SLI_STATUS_CRITICAL
    )
    # no samples -> ok
    assert (
        evaluate_sli("turn", {"total": 0, "success_rate": 1.0, "p95_s": 0.0}, slo)["status"]
        == SLI_STATUS_OK
    )


def test_llm_tool_retrieval_evaluation() -> None:
    slo = SLOConfig(
        llm_error_max=0.05, tool_error_max=0.10, retrieval_error_max=0.10, warn_factor=0.5
    )
    assert (
        evaluate_sli("llm", {"total": 100, "error_rate": 0.02, "p95_s": 1.0}, slo)["status"]
        == SLI_STATUS_OK
    )
    assert (
        evaluate_sli("llm", {"total": 100, "error_rate": 0.04, "p95_s": 1.0}, slo)["status"]
        == SLI_STATUS_WARN
    )
    assert (
        evaluate_sli("llm", {"total": 100, "error_rate": 0.08, "p95_s": 1.0}, slo)["status"]
        == SLI_STATUS_CRITICAL
    )
    assert (
        evaluate_sli("llm", {"total": 100, "error_rate": 0.01, "p95_s": 40.0}, slo)["status"]
        == SLI_STATUS_CRITICAL
    )
    # at the objective boundary the budget is not yet exceeded -> warn
    assert (
        evaluate_sli("tool", {"total": 10, "error_rate": 0.10, "p95_s": 0.5}, slo)["status"]
        == SLI_STATUS_WARN
    )
    # strictly over the objective -> critical
    assert (
        evaluate_sli("tool", {"total": 10, "error_rate": 0.11, "p95_s": 0.5}, slo)["status"]
        == SLI_STATUS_CRITICAL
    )
    assert (
        evaluate_sli("retrieval", {"total": 10, "error_rate": 0.09, "p95_s": 0.5}, slo)["status"]
        == SLI_STATUS_WARN
    )


def test_evaluate_all_overall_rollup() -> None:
    slo = SLOConfig()
    healthy = _snap({"turn.completed": 100})
    assert evaluate_all(healthy, slo)["status"] == SLI_STATUS_OK
    assert overall_is_healthy(evaluate_all(healthy, slo))

    failing = _snap({"turn.completed": 90, "turn.failed": 10})
    report = evaluate_all(failing, slo)
    assert report["status"] == SLI_STATUS_CRITICAL
    assert not overall_is_healthy(report)

    # persistence failure forces critical even with clean metrics
    assert evaluate_all(healthy, slo, persistence_ok=False)["status"] == SLI_STATUS_CRITICAL


def test_evaluate_all_telemetry_ok_input() -> None:
    slo = SLOConfig()
    snap = _snap({"turn.completed": 100})
    assert evaluate_all(snap, slo, telemetry_ok=True)["status"] == SLI_STATUS_OK
    assert evaluate_all(snap, slo, telemetry_ok=False)["status"] == SLI_STATUS_CRITICAL


def test_load_slo_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LUMEN_SLO_TURN_SUCCESS_MIN", "0.90")
    monkeypatch.setenv("LUMEN_SLO_LLM_ERROR_MAX", "0.10")
    cfg = load_slo_config()
    assert cfg.turn_success_min == 0.90
    assert cfg.llm_error_max == 0.10
    assert cfg.tool_error_max == 0.10  # default preserved

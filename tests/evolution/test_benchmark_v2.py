"""Benchmark v2 tests — reproducibility, determinism, controlled variables,
and separation of Runtime vs Teaching metrics."""

from __future__ import annotations

import pytest

from lumen.evolution.benchmark import BENCHMARK_VERSION, SCENARIOS, run_benchmark
from lumen.evolution.providers import LegacyProvider


@pytest.mark.asyncio
async def test_benchmark_version_is_v2():
    assert BENCHMARK_VERSION == "v2"


@pytest.mark.asyncio
async def test_benchmark_covers_reference_scenarios():
    ids = {s.id for s in SCENARIOS}
    assert "single_tool_call" in ids
    assert "long_session_continuity" in ids
    assert "assessment" in ids


@pytest.mark.asyncio
async def test_benchmark_emits_reproducible_records():
    run = await run_benchmark([LegacyProvider()], reps=2, seed=1)
    assert len(run.reports) == len(SCENARIOS) * 2
    rec = run.reports[0].record
    assert rec.provider_id == "legacy"
    assert rec.benchmark_version == "v2"
    assert rec.model == "scripted-seeded"
    assert rec.seed == 1
    assert rec.metrics["rt_task_success"] is not None


@pytest.mark.asyncio
async def test_benchmark_is_deterministic_across_seed_runs():
    run_a = await run_benchmark([LegacyProvider()], reps=2, seed=1)
    run_b = await run_benchmark([LegacyProvider()], reps=2, seed=1)
    a_provider = run_a.by_provider()["legacy"][0]
    b_provider = run_b.by_provider()["legacy"][0]
    assert a_provider.record.lineage_key() == b_provider.record.lineage_key()


@pytest.mark.asyncio
async def test_determinism_metric_is_computed_across_reps():
    run = await run_benchmark([LegacyProvider()], reps=3, seed=1)
    for rep in run.reports:
        assert rep.metrics.runtime.determinism == 1.0  # scripted model → replay stable


@pytest.mark.asyncio
async def test_runtime_and_teaching_metrics_are_reported_separately():
    run = await run_benchmark([LegacyProvider()], reps=1, seed=1)
    metrics = run.reports[0].metrics.as_dict()
    assert "rt_latency" in metrics
    assert "teach_decision_correctness" in metrics
    # No fused single score exists.
    assert "score" not in metrics


@pytest.mark.asyncio
async def test_benchmark_never_touches_production_provider():
    from lumen.profile import PRODUCTION_PROFILE

    # Running the benchmark must not mutate the production profile.
    before = PRODUCTION_PROFILE
    await run_benchmark([LegacyProvider()], reps=1, seed=1)
    assert PRODUCTION_PROFILE is before

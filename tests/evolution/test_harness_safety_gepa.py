"""Evolution Harness / safety / GEPA tests."""

from __future__ import annotations

import pytest

from lumen.evolution.benchmark import run_benchmark
from lumen.evolution.fakes import make_standard_tools
from lumen.evolution.gepa import GepaFeasibility, feasibility
from lumen.evolution.harness import EvolutionCandidate, EvolutionHarness, Generation, MutationTarget
from lumen.evolution.pareto import ParetoArchive
from lumen.evolution.providers import LegacyProvider
from lumen.evolution.safety import (
    ALLOWED_LIFECYCLE_TARGETS,
    MutationProposal,
    SafetyGate,
)

# ── Evolution Harness objects ─────────────────────────────────────────────


def test_mutation_target_enum_is_phase1_whitelist():
    assert set(t.value for t in MutationTarget) == {
        "prompt",
        "teaching_policy",
        "context_policy",
        "provider_config",
        "graph_topology",
    }


def test_candidate_tracks_lineage_and_generation():
    cand = EvolutionCandidate(
        candidate_id="c1", parent_id="p0", generation=1, mutations={MutationTarget.PROMPT: "x"}
    )
    assert cand.parent_id == "p0"
    assert cand.generation == 1


def test_generation_has_candidates_and_lineage():
    gen = Generation(
        number=1, candidates=[EvolutionCandidate(candidate_id="a")], parent_lineage=["p0"]
    )
    assert gen.number == 1
    assert gen.candidates[0].candidate_id == "a"


@pytest.mark.asyncio
async def test_harness_evaluate_maps_benchmark_to_evaluation_results():
    run = await run_benchmark([LegacyProvider()], reps=1, seed=1)
    harness = EvolutionHarness(benchmark=None, target_provider_ids=["legacy"])
    results = await harness.evaluate(run)
    assert results
    assert all(isinstance(r.metrics, dict) for r in results)


@pytest.mark.asyncio
async def test_harness_records_experiment():
    run = await run_benchmark([LegacyProvider()], reps=1, seed=1)
    harness = EvolutionHarness(benchmark=None, target_provider_ids=["legacy"])
    recs = [r.record for r in run.reports]
    exp = harness.record_experiment("e-1", recs, seed=1)
    assert exp.benchmark_version == "v2"
    assert len(harness.experiments()) == 1


# ── Safety / Goal 10 ──────────────────────────────────────────────────────


def test_allowed_whitelist_matches_phase1():
    assert ALLOWED_LIFECYCLE_TARGETS == {
        "prompt",
        "teaching_policy",
        "context_policy",
        "provider_config",
        "graph_topology",
    }


def test_safety_gate_allows_whitelisted_targets():
    gate = SafetyGate()
    assert gate.allow(MutationProposal("prompt", "system", "be concise"))
    assert gate.allow(MutationProposal("teaching_policy", "scaffold_strategy", "socratic"))
    assert gate.allow(MutationProposal("provider_config", "temperature", 0.1))


def test_safety_gate_blocks_production():
    gate = SafetyGate()
    assert not gate.allow(MutationProposal("production", "provider", "X"))
    assert not gate.allow(MutationProposal("graph_topology", "benchmark_edges", "X"))
    assert not gate.allow(MutationProposal("provider_config", "promote_to_production", "X"))


def test_safety_gate_blocks_test_oracle_and_arbitrary():
    gate = SafetyGate()
    assert not gate.allow(MutationProposal("test_oracle", "judge", "X"))
    assert not gate.allow(MutationProposal("arbitrary", "repo", "x"))


def test_safety_gate_records_decisions_for_audit():
    gate = SafetyGate()
    gate.allow(MutationProposal("prompt", "system", "x"))
    gate.allow(MutationProposal("production", "provider", "y"))
    assert len(gate.decisions) == 2
    assert gate.decisions[0]["decision"] == "allow"
    assert gate.decisions[1]["decision"] == "deny"


@pytest.mark.asyncio
async def test_recursive_loop_updates_pareto_archive_from_sandboxed_eval():
    from lumen.evolution.safety import RecursiveEvolutionLoop

    archive = ParetoArchive()

    async def eval_fn(cand):
        return {"rt_output_quality": 1.0, "rt_step_count": 3}

    loop = RecursiveEvolutionLoop(
        produce_candidates=lambda: [EvolutionCandidate(candidate_id=f"e{i}") for i in range(2)],
        evaluate=eval_fn,
        archive=archive,
    )
    await loop.step(0)
    # Both candidates have equal metrics → neither dominates → both on frontier.
    assert len(archive.members()) == 2


# ── GEPA / Goal 9 ─────────────────────────────────────────────────────────


def test_gepa_feasibility_recorded():
    f = feasibility()
    assert isinstance(f, GepaFeasibility)
    assert "teaching_policy" in f.integration_points
    assert "graph_topology" in f.integration_points


def test_gepa_verdict_is_contained():
    f = feasibility()
    assert "FEASIBLE" in f.verdict
    assert "NOT recommended" in f.verdict

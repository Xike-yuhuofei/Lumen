"""Teaching Architecture Experiment — Phase-3 discriminant gates.

Pins the *reproducible* incremental-value seams the goal's phase-3 experiment
must show for Candidate B, on isolated stores with deterministic learners:

* ``session_continuity``      — interrupted multi-session learner reproduces the
  single-run classroom outcome (mastered / attempts / effects), no duplicate
  decisions, no duplicate effects.
* ``decision_ledger``         — every decision is a persisted, versioned,
  replayable PolicyDecision with full effect lineage.
* ``cost_scaling``            — Candidate B's deterministic-decision LLM-call
  overhead is below A's and the gap grows with curriculum length.

These are repeatable, not "designed to help B beat A": A is never modified, the
engine/learners/materials/metrics/conditions are untouched, and the cost axis
compares both candidates on identical shared conditions.
"""

from __future__ import annotations

import pytest

from .phase3_experiments import cost_scaling, decision_ledger, session_continuity

__all__: list[str] = []


@pytest.mark.asyncio
async def test_phase3_session_continuity_matches_single_run(eval_env):
    """B over an interrupted multi-session learner == one uninterrupted run."""
    result = await session_continuity(path_root=eval_env)
    assert result["split"]["completed"], "the interrupted multi-session learner did not complete"
    assert result["action_sequence_match"], (
        "a fresh graph over the durable ledger diverged from the single-run action"
        " sequence — long-horizon continuity is broken"
    )
    assert result["no_duplicate_effects"], "duplicate authoritative effects across sessions"
    assert result["no_duplicate_decisions"], "the same decision_id was reused"
    assert result["continuity_match"], "mastered/attempts/effects diverged across sessions"
    assert result["n_sessions"] >= 2, "scenario did not actually split into sessions"


@pytest.mark.asyncio
async def test_phase3_all_decisions_committed_replayable_with_lineage(eval_env):
    """Every Candidate-B decision is an immutable, persisted, versioned,
    replayable PolicyDecision carrying effect lineage."""
    result = await decision_ledger(path_root=eval_env)
    assert result["decisions"] >= 1
    assert result["all_persisted"], "some decisions were not committed to the durable ledger"
    assert result["all_replayable"], "some decisions could not be reconstructed via Decision Replay"
    assert result["policy_version"], "decisions carry no policy_version tag"
    assert result["policy_versions"].get(result["policy_version"], 0) >= 1
    assert result["lineage_ok"], "a graded effect is not linked to its decision_id"


@pytest.mark.asyncio
async def test_phase3_cost_gap_grows_with_curriculum(eval_env):
    """Candidate B's LLM-call overhead < A's, and the gap widens on the longer
    curriculum (deterministic decisions are free; content fills scale sub-linearly)."""
    result = await cost_scaling(path_root=eval_env)
    mats = result["materials"]
    for mid, m in mats.items():
        assert m["b_mean_llm_calls"] < m["a_mean_llm_calls"], (
            f"Candidate B is not cheaper than A on {mid}"
        )
    assert mats[result["long"]]["kp_count"] > mats[result["short"]]["kp_count"]
    assert result["cost_gap_grows_with_curriculum"], (
        "B/A call ratio did not fall on the longer curriculum"
    )
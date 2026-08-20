"""Teaching Architecture Experiment — Phase-4c Real-Learner gates.

Pins what phase-4c must demonstrate, on isolated stores with the deterministic
strategy-sensitive learner, so the conclusion is reproducible rather than asserted:

* ``learner_discriminates_strategy`` — the realistic learner must react
  measurably differently to scaffolded teaching vs assessment-only drilling,
  otherwise the A/B matrix cannot discriminate pedagogy (a vacuous null).
* ``learner_realism_matrix_parity`` — under that discriminating learner,
  Candidate A and Candidate B still execute identical teaching and reach the
  same designated outcomes, i.e. B's architecture does not yield a learning
  increment because it does not change the pedagogy.
* ``multi_session_continuity_preserves_outcome`` — Candidate B's durable
  multi-session continuity returns the same outcome as a single uninterrupted
  run (it preserves state; it does not add learning value).

A is never modified; the engine / metrics / evaluation conditions are untouched.
"""

from __future__ import annotations

import pytest

from .phase4c_experiments import (
    learner_realism_matrix,
    multi_session_increment,
    strategy_discrimination_probe,
)

__all__: list[str] = []


def test_phase4c_learner_discriminates_strategy():
    """The realistic learner can tell scaffolded teaching from assessment-only
    drilling — so a real A/B pedagogy difference would be observable."""
    probe = strategy_discrimination_probe(samples=40)
    assert probe["learner_discriminates_strategy"], (
        "strategy-sensitive learner did not react to teaching strategy; the "
        "phase-4c matrix would be unable to discriminate pedagogy"
    )
    assert probe["scaffolded_success_ratio"] > probe["assessment_only_success_ratio"]


@pytest.mark.asyncio
async def test_phase4c_learner_realism_matrix_parity(eval_env):
    """Under the discriminating learner, A and B still execute identical teaching
    with identical designated outcomes (B's graph does not change the pedagogy)."""
    matrix = await learner_realism_matrix(path_root=eval_env, max_rounds=800)
    assert matrix["n_cells"] >= 2, "matrix too small to be discriminating"
    assert matrix["outcome_equal_across_matrix"], (
        "outcome parity between A and B did not hold under the realistic learner"
    )
    assert matrix["action_sequence_equal_across_matrix"], (
        "A and B executed different teaching sequences under the realistic learner"
    )
    assert matrix["strategy_sequence_equal_across_matrix"], (
        "A and B delivered different strategy strategy-signals under the realistic learner"
    )
    assert matrix["completed_cells"] > 0, (
        "no cell reached completion — the parity cannot be asserted on empty mastery"
    )


@pytest.mark.asyncio
async def test_phase4c_multi_session_continuity_preserves_outcome(eval_env):
    """B's multi-session continuity returns the SAME outcome as one uninterrupted
    run (it preserves teaching state but adds no learning increment)."""
    ms = await multi_session_increment(path_root=eval_env, max_rounds=800)
    assert ms["continuity_preserves_outcome"], (
        "splitting an episode across sessions changed the learner outcome"
    )
    inc = ms["increment_from_continuity"]
    assert all(v == 0 for v in (inc["mastered"],)) and inc["retention"] == 0 and inc["transfer"] == 0, (
        f"continuity added a learning increment: {inc}"
    )
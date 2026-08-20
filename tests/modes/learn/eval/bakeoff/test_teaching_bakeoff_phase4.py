"""Teaching Architecture Experiment — Phase-4 real-teaching-value gates.

Pins what the phase-4 experiment must demonstrate, on isolated stores with the
deterministic learners, so the conclusion is reproducible rather than asserted:

* ``outcome_equality`` — across the FULL (material x learner) matrix, Candidate
  A and Candidate B yield IDENTICAL designated outcome variables (independent
  success / retention / transfer / time-to-mastery), under symmetric conditions.
* ``completing_cells_execute_identically`` — on every cell that COMPLETES
  (i.e. except the unstable 'guessing' learner), the two architectures execute
  byte-identical action sequences, i.e. the graph changes the representation of
  the loop, not the pedagogy.
* ``unrecoverable_cells_both_deny_mastery`` — on the guessing cells, where
  mastery must NOT be granted, Candidate A and Candidate B both correctly leave
  the goal unfinished with identical mastered counts (the only fingerprint
  divergence is loop pacing, not a learning difference).
* ``real_llm_probe_shape`` — the environment's real-LLM availability is
  reported from the credential resolver, not assumed.

A is never modified; the engine / learners / materials / metrics / evaluation
conditions and the closed Gates are untouched.
"""

from __future__ import annotations

import pytest

from .phase4_experiments import (
    learning_outcomes_matrix,
    probe_real_llm,
)

__all__: list[str] = []


@pytest.mark.asyncio
async def test_phase4_outcome_equality_across_matrix(eval_env):
    """Candidate B's graph yields the SAME designated learning outcomes as A on
    every (material x learner) cell — no measurable learning-value increment."""
    matrix = await learning_outcomes_matrix(path_root=eval_env, max_rounds=400)
    assert matrix["n_cells"] >= 8, "matrix is too small to be discriminating"
    assert matrix["outcome_equal_across_matrix"], (
        "delta-free outcome equality (independent success / retention / transfer / "
        "time-to-mastery) between A and B did not hold across every cell"
    )


@pytest.mark.asyncio
async def test_phase4_completing_cells_execute_identically(eval_env):
    """On every cell that reaches COMPLETE, A and B run byte-identical action
    sequences (graph = representation of the loop, not different pedagogy)."""
    matrix = await learning_outcomes_matrix(path_root=eval_env, max_rounds=400)
    completing = [c for c in matrix["cells"] if c["completion"]["a"] and c["completion"]["b"]]
    assert completing, "no completing cells to compare"
    assert all(c["action_sequence_equal"] for c in completing), (
        "a completing cell executed a different teaching sequence between A and B"
    )


@pytest.mark.asyncio
async def test_phase4_unrecoverable_cells_both_deny_mastery(eval_env):
    """The unstable 'guessing' learner must NOT be granted mastery by either
    architecture; the only observed fingerprint differences are non-learning."""
    matrix = await learning_outcomes_matrix(path_root=eval_env, max_rounds=400)
    guessing = [c for c in matrix["cells"] if c["learner"] == "guessing"]
    assert guessing, "guessing cells missing"
    for cell in guessing:
        assert not cell["completion"]["a"] and not cell["completion"]["b"], (
            "an unrecoverable learner was incorrectly granted COMPLETE"
        )
        assert cell["outcomes"]["a"]["mastered"] == cell["outcomes"]["b"]["mastered"], (
            "A and B awarded different mastery on the unstable learner"
        )
        # A fingerprint difference is allowed ONLY on these cells and only if the
        # retained outcome (completion + mastered) is identical.
        assert cell["outcome_equal"], "outcome divergence on the guessing cell"


def test_phase4_real_llm_probe_shape():
    """The decisive real-LLM availability is resolved from credentials (env),
    never assumed; its absence is recorded, not silently fabricated."""
    probe = probe_real_llm()
    assert isinstance(probe["real_llm_available"], bool)
    assert isinstance(probe["configured_providers"], list)
    assert probe["n_configured"] == len(probe["configured_providers"])
    assert isinstance(probe["note"], str) and probe["note"]
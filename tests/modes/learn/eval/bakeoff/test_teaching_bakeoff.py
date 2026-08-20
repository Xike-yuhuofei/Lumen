"""Teaching Architecture Bake-off — reproducibility + parity gate.

This is the "repeatable pytest" half of the Bake-off.  It runs a representative
(material x learner) subset of the shared eval harness for both candidates and
pins two properties that any *future* PROMOTE decision must not silently break:

1. **Reproducibility** — the same (candidate, material, learner) yields the same
   teaching record every run, so the comparison is auditable and diff-able.
2. **Teaching parity after the gap-closure work** — Candidate B (the Teaching
   Session Graph) now closes the loop for the same learners Candidate A
   completes and diagnoses/remediates the same registered misconceptions.  The
   original "A closes, B does not" split was the exact evidence the parity work
   removed; these gates keep B's parity from silently regressing.

Run:

    .venv/bin/python -m pytest tests/modes/learn/eval/bakeoff/test_teaching_bakeoff.py -q
"""

from __future__ import annotations

import pytest

from lumen.modes.learn.adapters.storage import LearningStore

from ..harness import run_loop
from ..learners import MisconceptionLearner, StrongLearner, WeakLearner
from ..materials import BENCHMARK_SET
from ._candidate_b import run_loop_b
from .metrics import compute_probes, record_metrics

# A bounded subset keeps the gate fast: 2 materials x 3 learners x 2 candidates.
_MATERIAL_IDS = ("zhongcao", "textile")
_LEARNERS = (StrongLearner, WeakLearner, MisconceptionLearner)
_MAX_ROUNDS = 150


@pytest.mark.asyncio
@pytest.mark.parametrize("material_id", _MATERIAL_IDS)
@pytest.mark.parametrize("learner_cls", _LEARNERS)
async def test_bakeoff_comparison_is_reproducible(eval_env, material_id, learner_cls):
    """Same (candidate x material x learner) -> identical teaching record."""
    material = BENCHMARK_SET[material_id]

    def path(cand: str) -> str:
        return f"repro_{material_id}_{learner_cls().name}_{cand}"

    la = learner_cls()
    a1 = await run_loop(material, la, path_id=path("a1"), store_root=eval_env, max_rounds=_MAX_ROUNDS)
    la2 = learner_cls()
    a2 = await run_loop(material, la2, path_id=path("a2"), store_root=eval_env, max_rounds=_MAX_ROUNDS)
    lb = learner_cls()
    b1 = await run_loop_b(material, lb, path_id=path("b1"), store_root=eval_env, max_rounds=_MAX_ROUNDS)
    lb2 = learner_cls()
    b2 = await run_loop_b(material, lb2, path_id=path("b2"), store_root=eval_env, max_rounds=_MAX_ROUNDS)

    def probes_for(learner, path_id: str):
        store = LearningStore(root=eval_env)
        progress = store.load(path_id)
        return compute_probes(learner, material, progress) if progress is not None else (None, None)

    def sig(rec, probes):
        return {
            "completed": rec.completed,
            "steps": len(rec.rounds),
            "actions": [r.get("action") for r in rec.rounds],
            "mastered": rec.final_state.get("counts", {}).get("mastered", 0),
            "retention": probes[0],
            "transfer": probes[1],
        }

    assert sig(a1, probes_for(la, path("a1"))) == sig(a2, probes_for(la2, path("a2"))), "Candidate A not reproducible"
    assert sig(b1, probes_for(lb, path("b1"))) == sig(b2, probes_for(lb2, path("b2"))), "Candidate B not reproducible"


@pytest.mark.asyncio
async def test_bakeoff_b_matches_a_completion(eval_env):
    """After the parity-gap closure Candidate B closes the loop for the same
    learners Candidate A completes (strong / weak / misconception); neither
    completes the deliberately unstable GuessingLearner. This replaces the
    pre-fix "A completes, B does not" split — that asymmetry was the exact
    evidence the parity work removed."""
    for material_id in _MATERIAL_IDS:
        material = BENCHMARK_SET[material_id]
        for learner_cls in (StrongLearner, WeakLearner, MisconceptionLearner):
            a = await run_loop(
                material, learner_cls(), path_id=f"gate_a_{material_id}_{learner_cls().name}",
                store_root=eval_env, max_rounds=_MAX_ROUNDS,
            )
            b = await run_loop_b(
                material, learner_cls(), path_id=f"gate_b_{material_id}_{learner_cls().name}",
                store_root=eval_env, max_rounds=_MAX_ROUNDS,
            )
            assert a.completed, f"A failed on {material_id} x {learner_cls().name}"
            assert b.completed, (
                f"Candidate B regressed: no longer completes {material_id} x "
                f"{learner_cls().name} after the parity-gap closure."
            )


@pytest.mark.asyncio
async def test_bakeoff_b_matches_a_misconception_remediation(eval_env):
    """Candidate B now diagnoses and remediates the same registered
    misconceptions as Candidate A (formerly B passed an empty misconception id
    and its remediation path was unreachable)."""
    zhongcao = BENCHMARK_SET["zhongcao"]
    a = await run_loop(
        zhongcao, MisconceptionLearner(), path_id="d_a_mis", store_root=eval_env, max_rounds=_MAX_ROUNDS
    )
    b = await run_loop_b(
        zhongcao, MisconceptionLearner(), path_id="d_b_mis", store_root=eval_env, max_rounds=_MAX_ROUNDS
    )
    am = record_metrics(a, candidate="a")
    bm = record_metrics(b, candidate="b_virgin")
    assert am["diagnosis_detected"] > 0, "Candidate A should detect the registered misconception"
    assert bm["diagnosis_detected"] > 0, (
        "Candidate B regressed: no longer detects any registered misconception "
        "after the parity-gap closure."
    )
    # Diagnosis and remediation must be at least as complete as A's.
    assert bm["diagnosis_detected"] >= am["diagnosis_detected"]
    assert bm["remediation_steps"] >= 1
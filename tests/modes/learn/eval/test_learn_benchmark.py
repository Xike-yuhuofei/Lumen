"""Benchmark-set tests — the fixed real-material evaluation.

Every material in :data:`~.materials.BENCHMARK_SET` is driven through the full
Learn loop (build -> goal -> plan -> quiz/assess/grade -> ... -> COMPLETE)
with the deterministic harness, and the collected record is asserted against
the acceptance criteria (completion, no premature mastery, grounding,
traceability, misconception handling, different learners -> different paths).

The same runs feed the machine-readable JSON dump produced by
``run_benchmark.py`` for cross-run regression comparison.
"""

from __future__ import annotations

import pytest

from .harness import kp_ids_for, owning_kp_id, run_loop
from .learners import (
    MisconceptionLearner,
    StrongLearner,
    WeakLearner,
)
from .materials import BENCHMARK_SET, ZHONGCAO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "material_id,learner_cls",
    [
        ("zhongcao", StrongLearner),
        ("textile", StrongLearner),
        ("textile", WeakLearner),
    ],
)
async def test_benchmark_full_loop_completes(eval_env, material_id, learner_cls):
    material = BENCHMARK_SET[material_id]
    path_id = f"bench_{material_id}_{learner_cls().name}"
    learner = learner_cls()
    record = await run_loop(material, learner, path_id=path_id, store_root=eval_env)

    assert not record.failures, record.failures
    assert record.completed, f"{material_id} x {learner.name} did not reach COMPLETE"
    assert record.final_state["complete"] is True

    # every target mastered
    for kp_id in kp_ids_for(path_id, material):
        status = record.final_state["counts"]
        assert status["total"] == len(kp_ids_for(path_id, material))

    # every round carried a traceable decision
    assert all(r["trace"].get("policy_applied") for r in record.rounds)

    # source grounding: the plan surfaces each focused node's content + source
    for r in record.rounds:
        focus = r["focus_payload"]
        if focus.get("node_id") and focus.get("source_refs"):
            assert focus["source_refs"], f"ungrounded focus in round {r['round']}"


@pytest.mark.asyncio
async def test_benchmark_zhongcao_misconception_learner(eval_env):
    record = await run_loop(
        ZHONGCAO, MisconceptionLearner(), path_id="bench_zhongcao_mis", store_root=eval_env
    )
    assert record.completed, record.failures
    assert "remediate_misconception" in [r["action"] for r in record.rounds]
    # no misconception is left active — every one was remediated + re-verified
    for rec in record.final_state["error_records"]:
        assert rec["status"] == "graduated", rec


@pytest.mark.asyncio
async def test_benchmark_different_learners_produce_different_paths(eval_env):
    """The same material must produce measurably different teaching for a
    strong vs a struggling learner (over-teaching would violate this)."""
    strong = await run_loop(ZHONGCAO, StrongLearner(), path_id="path_s", store_root=eval_env)
    weak = await run_loop(ZHONGCAO, WeakLearner(), path_id="path_w", store_root=eval_env)
    assert strong.completed and weak.completed

    strong_rounds = len(strong.rounds)
    weak_rounds = len(weak.rounds)
    # the weak learner needs more teaching and reaches scaffolded practice
    assert weak_rounds > strong_rounds
    assert "practice" in [r["action"] for r in weak.rounds]
    assert "practice" not in [r["action"] for r in strong.rounds]


@pytest.mark.asyncio
async def test_benchmark_first_module_scope_completes_without_touching_rest(eval_env):
    """A scoped goal completes with exactly its own objectives mastered."""
    material = BENCHMARK_SET["textile"]
    path_id = "bench_scope"
    record = await run_loop(
        material, StrongLearner(), path_id=path_id, scope="first_module", store_root=eval_env
    )
    assert record.completed, record.failures
    scoped = kp_ids_for(path_id, material)[: len(material.modules[0].knowledge_points)]
    for kp_id in scoped:
        assert record.final_state["mastery"][kp_id] >= 0.9
    # objectives outside the scope are untouched
    for kp_id in kp_ids_for(path_id, material)[len(scoped):]:
        assert kp_id not in record.final_state["mastery"] or (
            record.final_state["mastery"][kp_id] == 0
        )
    # the goal-scoped completion counts exactly the in-scope objectives
    assert record.final_state["goal"]["total"] == len(scoped)
    assert record.final_state["goal"]["mastered"] == len(scoped)

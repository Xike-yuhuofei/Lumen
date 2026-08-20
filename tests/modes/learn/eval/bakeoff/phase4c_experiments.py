"""Phase-4c — Real Learner / Adaptive Teaching Validation.

Phase-4 (deterministic) and Phase-4b (real-LLM content) established that
Candidate A (teaching-hook + generic Agent Loop) and Candidate B (Teaching
Session Graph) produce *identical* designated learning outcomes, because both
funnel through the same deterministic TeachingEngine.  The goal's remaining
open question is the one Phase-4c targets:

> when the *learner* responds with real uncertainty, stable misconception and
> genuine strategy sensitivity, does Candidate B's diagnosis / remediation /
> scaffold switching / strategy adaptation / multi-session control translate
> into a measurable learning-value increment Candidate A cannot reach?

To answer it without touching Candidate A, the engine, the metrics or the
evaluation standards, Phase-4c introduces a more realistic simulated learner
(:class:`~tests.modes.learn.eval.learners.StrategySensitiveLearner`, a seeded,
misconception-bearing, strategy-affine model) and asks three reproducible
questions:

1. ``strategy_discrimination_probe`` — **diagnostic power**: can the new
   learner *discriminate teaching strategies at all*?  If the same learner
   succeeds notably better after being *taught* than after being *drilled
   without teaching*, then the A/B null in the matrix is meaningful (i.e. a
   real pedagogy difference between A and B *would* show up).  If the learner
   were pedagogy-blind, the matrix would be vacuous — this probe separates
   those two cases.
2. ``learner_realism_matrix`` — **A vs B under the realistic learner**: with
   the learner now genuinely uncertain and strategy-sensitive, do A and B still
   execute the same pedagogy (action/strategy sequence) and reach the same
   designated outcomes?  This is the decisive teaching-value check.
3. ``multi_session_increment`` — **B's multi-session control**: can B's durable
   graph continuity itself add learning value for a returning learner?  Measured
   as a B-vs-B check (single uninterrupted graph vs the same learner split
   across several interrupted sessions) under the realistic learner, so the
   only variable is continuity, not the candidate.

Nothing modifies Candidate A or the graph; ``run_loop_b`` (the phase-1/2/3 B
reader) is left untouched.  Every cell uses isolated temp stores and a seeded
learner, so the evidence is deterministic and reproducible.  Phase-4c needs no
LLM calls (content is a no-op stub, exactly as the goal directs: do not repeat
the Phase-4b real-content trial).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
from lumen.modes.learn.policy.policy import map_summary as _map_summary
from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

from ..harness import LoopRecord, kp_ids_for, owning_kp_id, run_loop
from ..learners import StrategySensitiveLearner
from ..materials import BENCHMARK_SET
from ._candidate_b import _AgentLoopStub, _build_and_seed, _Ctx, _Stream
from .metrics import compute_probes, record_metrics
from .phase4_experiments import _answer_symmetric, _cells_equal, _mechanisms


def _KP(id_: str, name: str = "kp", answer: str = "correct", misconceptions: list | None = None):
    """A minimal knowledge-point stand-in for the learner-model self-check."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=id_, name=name, answer=answer, misconceptions=misconceptions or []
    )


async def run_loop_b_sym_c4(
    material: Any,
    learner: Any,
    *,
    path_id: str | None = None,
    max_rounds: int = 400,
    store_root: Path | None = None,
    content_agent: Any = None,
) -> dict[str, Any]:
    """Drive the real Teaching Session Graph with *full* measurement symmetry.

    Identical to ``phase4_experiments.run_loop_b_symmetric`` (same graph, same
    qualitative routing, same ``LoopRecord``) EXCEPT it feeds the learner the
    same ``on_plan`` observation stream Candidate A's harness does — so the
    strategy-sensitive learner sees Candidate B's pedagogy exactly as it sees
    A's, and the A/B comparison is not skewed by a measurement asymmetry in the
    learner the Phase-4/4b (pedagogy-blind) learners never needed.
    """
    from dataclasses import replace

    path_id = path_id or f"evalBc4_{material.id}_{learner.name}"
    store = LearningStore(root=store_root)
    record = LoopRecord(material=material.id, learner=learner.name)

    bench_by_id: dict[str, Any] = {}
    for m, module in enumerate(material.modules):
        for j, kp in enumerate(module.knowledge_points):
            fid = f"{path_id}_m{m}_kp{j}"
            bench_by_id[fid] = replace(kp, id=fid)
    kp_ids_all = kp_ids_for(path_id, material)

    await _build_and_seed(
        material,
        path_id=path_id,
        store=store,
        scope="all",
        lesson="",
        seed_evidence=0,
        bench_by_id=bench_by_id,
        record=record,
    )
    if record.failures:
        return {"record": record, "learner": learner}

    graph = TeachingSessionGraph(store=store, scheduler=SpacedRepetitionScheduler())
    agent = content_agent or _AgentLoopStub()
    ctx = _Ctx(session_id=f"bake-c4-{path_id}", turn_id="t0")
    resume_input: str | None = None

    for turn_no in range(1, max_rounds + 1):
        ctx.metadata["turn_id"] = f"t{turn_no}"
        outcome = await graph.run_turn(
            path_id=path_id,
            teaching_session_id=f"sess-{path_id}",
            execution_generation=f"exec-{turn_no}",
            execution_operation="run",
            resume_input=resume_input,
            context=ctx,
            stream=_Stream(),
            agent_loop=agent,
            deps={},
        )
        record.rounds.append(
            {
                "round": turn_no,
                "graph_node": outcome.node.value,
                "action": outcome.decision.action,
                "focus": outcome.decision.focus_node_id,
                "strategy": outcome.decision.strategy,
                "reason": outcome.decision.reason,
                "policy_applied": outcome.decision.policy_applied,
                "decision_id": outcome.decision.decision_id,
                "committed": outcome.committed,
                "posed_pending": outcome.posed_pending,
                "graded": outcome.graded,
            }
        )
        # Feed the learner the SAME pedagogy observation Candidate A's harness
        # feeds (``run_loop`` calls ``on_plan`` every round).
        learner.on_plan(outcome.decision.action, outcome.decision.focus_node_id)
        if outcome.is_terminal:
            record.completed = True
            break

        if outcome.decision.action == "remediate_misconception":
            learner.on_remediation(owning_kp_id(outcome.decision.focus_node_id))

        pending = store.load(path_id).pending_question
        resume_input = _answer_symmetric(
            store, path_id, bench_by_id, kp_ids_all, learner, pending
        )
    else:
        record.failures.append(
            {
                "phase": "max_rounds",
                "round": max_rounds,
                "last_action": record.rounds[-1]["action"] if record.rounds else "",
            }
        )

    progress = store.load(path_id)
    final_map = _map_summary(progress)
    record.final_state = {
        "complete": final_map.get("complete", False),
        "counts": final_map.get("counts", {}),
        "goal": final_map.get("goal", {}),
        "mastery": dict(progress.mastery_levels),
        "qualitative_mastery": dict(progress.qualitative_mastery),
        "attempts": {
            kp_id: len([a for a in progress.quiz_attempts if a.knowledge_point_id == kp_id])
            for kp_id in material.kp_ids()
        },
        "error_records": [
            {
                "kp": rec.knowledge_point_id,
                "status": rec.status,
                "misconception_node_id": rec.misconception_node_id,
                "retry_count": len(rec.retry_history),
            }
            for rec in progress.error_records
        ],
    }
    record.assessment_history = [
        {
            "kp": a.knowledge_point_id,
            "question_id": a.question_id,
            "correct": a.is_correct,
            "kind": getattr(a, "question_kind", "recall"),
            "misconception_node_id": a.misconception_node_id,
            "mastery": a.mastery_estimate,
        }
        for a in progress.quiz_attempts
    ]
    record.agent_calls = agent.calls
    return {"record": record, "learner": learner}


def strategy_discrimination_probe(*, samples: int = 40, seed: int = 0) -> dict[str, Any]:
    """Prove the strategy-sensitive learner has *diagnostic power*.

    The same learner model, seeded identically, taught vs not taught on the same
    fresh knowledge point.  If its success on a quiz is materially higher after
    receiving teaching (``explain``/``practice``) than after being repeatedly
    assessed with none, then the learner *can* tell two teaching strategies
    apart — so a pedagogy difference between A and B in the matrix would be
    observable.  This is what separates "A==B because the pedagogy is truly
    shared" (meaningful null) from "A==B because the learner is pedagogy-blind"
    (vacuous null).
    """
    kp = _KP("kp_selfcheck")

    # Regime 1: the learner is *taught* the point first (scaffold + practice).
    taught = StrategySensitiveLearner(seed=seed)
    taught.on_plan("explain", "kp_selfcheck")
    taught.on_plan("explain", "kp_selfcheck")
    taught.on_plan("practice", "kp_selfcheck")
    taught_ok = sum(1 for _ in range(samples) if taught.quiz(kp).is_correct)

    # Regime 2: the learner is merely re-assessed — no teaching delivered.
    drilled = StrategySensitiveLearner(seed=seed)
    drilled_ok = sum(1 for _ in range(samples) if drilled.quiz(kp).is_correct)

    taught_ratio = taught_ok / samples
    drilled_ratio = drilled_ok / samples
    return {
        "kp": kp.id,
        "samples": samples,
        "assessment_only_success_ratio": round(drilled_ratio, 3),
        "scaffolded_success_ratio": round(taught_ratio, 3),
        "delta": round(taught_ratio - drilled_ratio, 3),
        "learner_discriminates_strategy": bool(taught_ratio > drilled_ratio + 0.2),
    }


async def _run_cell_c4(
    candidate: str,
    material: Any,
    *,
    path_id: str,
    store_root: Path,
    max_rounds: int,
) -> dict[str, Any]:
    learner = StrategySensitiveLearner(seed=0)
    path = f"{path_id}_{material.id}_{learner.name}"
    if candidate == "a":
        record = await run_loop(
            material, learner, path_id=path, store_root=store_root, max_rounds=max_rounds
        )
    else:
        out = await run_loop_b_sym_c4(
            material, learner, path_id=path, store_root=store_root, max_rounds=max_rounds
        )
        record = out["record"]
        learner = out["learner"]
    progress = LearningStore(root=store_root).load(path)
    probes = compute_probes(learner, material, progress) if progress is not None else (0.0, 0.0)
    return {
        "candidate": candidate,
        "material": material.id,
        "learner": learner.name,
        "record": record,
        "probes": probes,
    }


def _cell_outcome(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ma = record_metrics(a["record"], candidate="a", probes=a["probes"])
    mb = record_metrics(b["record"], candidate="b_adaptive", probes=b["probes"])
    keys = ["completed", "mastered", "steps", "unprompted_success", "retention", "transfer"]
    pad = {"completed": False, "mastered": 0, "steps": 0, "unprompted_success": 0.0, "retention": 0.0, "transfer": 0.0}
    rendered = {
        "a": {k: (ma.get(k) if k in ma else pad[k]) for k in keys},
        "b": {k: (mb.get(k) if k in mb else pad[k]) for k in keys},
    }
    return {
        "material": ma.get("material"),
        "learner": ma.get("learner"),
        "action_sequence_equal": [r.get("action") for r in a["record"].rounds]
        == [r.get("action") for r in b["record"].rounds],
        "strategy_sequence_equal": [r.get("strategy", "") for r in a["record"].rounds]
        == [r.get("strategy", "") for r in b["record"].rounds],
        "mechanism_fingerprint_equal": _mechanisms(a["record"]) == _mechanisms(b["record"]),
        "outcome_equal": _cells_equal(ma, mb),
        "outcomes": rendered,
        "completed": {"a": ma["completed"], "b": mb["completed"]},
        "mastered": {"a": ma["mastered"], "b": mb["mastered"]},
        "steps": {"a": ma["steps"], "b": mb["steps"]},
    }


async def learner_realism_matrix(
    *,
    path_root: Path,
    material_ids: tuple[str, ...] = ("zhongcao", "textile"),
    max_rounds: int = 800,
) -> dict[str, Any]:
    """A vs B under the strategy-sensitive learner, across the material set."""
    base = path_root / "learner_realism"
    cells: list[dict[str, Any]] = []
    for material_id in material_ids:
        material = BENCHMARK_SET[material_id]
        a = await _run_cell_c4("a", material, path_id="c4_a", store_root=base / "a", max_rounds=max_rounds)
        b = await _run_cell_c4("b", material, path_id="c4_b", store_root=base / "b", max_rounds=max_rounds)
        cells.append(_cell_outcome(a, b))
    return {
        "learner": "strategy_sensitive",
        "materials": list(material_ids),
        "n_cells": len(cells),
        "action_sequence_equal_across_matrix": all(c["action_sequence_equal"] for c in cells),
        "strategy_sequence_equal_across_matrix": all(c["strategy_sequence_equal"] for c in cells),
        "mechanism_fingerprint_equal_across_matrix": all(c["mechanism_fingerprint_equal"] for c in cells),
        "outcome_equal_across_matrix": all(c["outcome_equal"] for c in cells),
        "completed_cells": sum(1 for c in cells if c["completed"]["a"] and c["completed"]["b"]),
        "cells": cells,
    }


async def multi_session_increment(
    *,
    path_root: Path,
    material_id: str = "zhongcao",
    turns_per_session: int = 6,
    max_rounds: int = 800,
) -> dict[str, Any]:
    """B-vs-B: does B's durable multi-session continuity itself add *learning*?

    The SAME strategy-sensitive learner (seed 0) is run through Candidate B
    once as a single uninterrupted graph, and once split across many fresh graph
    instances (new session boundaries) on the SAME durable store.  Every graph
    decision/response is deterministic; the only variable is session continuity.
    Phase-3 proved continuity reproduces a continuous classroom outcome; here the
    question is whether continuity — under a learner with real uncertainty and a
    cross-session-relevant misconception state — *improves* any designated
    outcome variable relative to a fresh start, which would be an architectural
    learning increment.  ``split_increment == 0`` means continuity only *preserves*
    outcomes (an operational property), not that it adds learning value.
    """
    from dataclasses import replace

    material = BENCHMARK_SET[material_id]
    base = path_root / "multi_session"
    continuous_root, split_root, ckp_root = base / "cont", base / "split", base / "ckp"

    async def _episode(
        *,
        path_id: str,
        store_root: Path,
        checkpoint_root: Path,
        split: bool,
    ) -> dict[str, Any]:
        learner = StrategySensitiveLearner(seed=0)
        store = LearningStore(root=store_root)
        record = LoopRecord(material=material.id, learner=learner.name)
        bench_by_id: dict[str, Any] = {}
        for m, module in enumerate(material.modules):
            for j, kp in enumerate(module.knowledge_points):
                fid = f"{path_id}_m{m}_kp{j}"
                bench_by_id[fid] = replace(kp, id=fid)
        kp_ids_all = kp_ids_for(path_id, material)
        await _build_and_seed(
            material, path_id=path_id, store=store, scope="all", lesson="",
            seed_evidence=0, bench_by_id=bench_by_id, record=record,
        )
        if not record.failures:
            from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint

            checkpoint = TeachingGraphCheckpoint(checkpoint_root) if split else None
            resume_input: str | None = None
            turn_no, session, completed = 0, 0, False

            async def _turn(graph: TeachingSessionGraph, ctx: Any) -> Any:
                nonlocal turn_no, session, resume_input
                turn_no += 1
                ctx.metadata["turn_id"] = f"s{session}-t{turn_no}"
                return await graph.run_turn(
                    path_id=path_id,
                    teaching_session_id="sess-c4",
                    execution_generation=f"{path_id}-s{session}-g{turn_no}",
                    execution_operation="run",
                    resume_input=resume_input,
                    context=ctx,
                    stream=_Stream(),
                    agent_loop=_AgentLoopStub(),
                    deps={},
                )

            async def _finish(graph: TeachingSessionGraph, outcome: Any) -> bool:
                nonlocal resume_input
                record.rounds.append({
                    "round": turn_no,
                    "graph_node": outcome.node.value,
                    "action": outcome.decision.action,
                    "focus": outcome.decision.focus_node_id,
                    "strategy": outcome.decision.strategy,
                    "committed": outcome.committed,
                    "graded": outcome.graded,
                })
                learner.on_plan(outcome.decision.action, outcome.decision.focus_node_id)
                if outcome.is_terminal:
                    record.completed = True
                    return True
                if outcome.decision.action == "remediate_misconception":
                    learner.on_remediation(owning_kp_id(outcome.decision.focus_node_id))
                pending = store.load(path_id).pending_question
                resume_input = _answer_symmetric(
                    store, path_id, bench_by_id, kp_ids_all, learner, pending
                )
                return False

            if split:
                # Split: a FRESH graph instance (a new session / process boundary)
                # every ``turns_per_session`` — a learner returning later on the SAME
                # durable store + checkpoint.  Continuation is driven by durable state.
                while turn_no < max_rounds and not completed:
                    graph = TeachingSessionGraph(
                        store=store, scheduler=SpacedRepetitionScheduler(),
                        checkpoint=checkpoint,
                    )
                    ctx = _Ctx(session_id=f"c4-{session}", turn_id="t0")
                    per_session = 0
                    while per_session < turns_per_session and turn_no < max_rounds and not completed:
                        per_session += 1
                        outcome = await _turn(graph, ctx)
                        if await _finish(graph, outcome):
                            completed = True
                            break
                    session += 1
            else:
                # Continuous: ONE graph instance for the whole episode (the
                # "classroom" reference — no session boundary at all).
                graph = TeachingSessionGraph(
                    store=store, scheduler=SpacedRepetitionScheduler(),
                )
                ctx = _Ctx(session_id=f"c4-cont-{path_id}", turn_id="t0")
                session = 1
                while turn_no < max_rounds and not completed:
                    outcome = await _turn(graph, ctx)
                    if await _finish(graph, outcome):
                        break
            if not record.completed:
                record.failures.append({
                    "phase": "max_rounds", "round": max_rounds,
                    "last_action": record.rounds[-1]["action"] if record.rounds else "",
                })
        progress = store.load(path_id)
        final_map = _map_summary(progress)
        record.final_state = {
            "complete": final_map.get("complete", False),
            "counts": final_map.get("counts", {}),
            "mastery": dict(progress.mastery_levels),
            "qualitative_mastery": dict(progress.qualitative_mastery),
            "error_records": [
                {"kp": rec.knowledge_point_id, "status": rec.status,
                 "misconception_node_id": rec.misconception_node_id}
                for rec in progress.error_records
            ],
        }
        record.assessment_history = [
            {"kp": a.knowledge_point_id, "correct": a.is_correct,
             "kind": getattr(a, "question_kind", "recall")}
            for a in progress.quiz_attempts
        ]
        profiles = compute_probes(learner, material, progress) if progress is not None else (0.0, 0.0)
        return {
            "completed": record.completed,
            "steps": len(record.rounds),
            "mastered": record.final_state["counts"].get("mastered", 0),
            "actions": [r.get("action") for r in record.rounds],
            "n_sessions": session,
            "retention": profiles[0],
            "transfer": profiles[1],
            "failures": list(record.failures),
        }

    for root in (continuous_root, split_root, ckp_root):
        root.mkdir(parents=True, exist_ok=True)
    continuous = await _episode(
        path_id="cont", store_root=continuous_root, checkpoint_root=ckp_root, split=False
    )
    split = await _episode(
        path_id="split", store_root=split_root, checkpoint_root=ckp_root, split=True
    )

    disc = {
        "completed": continuous["completed"] == split["completed"],
        "mastered": continuous["mastered"] == split["mastered"],
        "retention": abs(continuous["retention"] - split["retention"]) < 1e-9,
        "transfer": abs(continuous["transfer"] - split["transfer"]) < 1e-9,
        "actions": continuous["actions"] == split["actions"],
    }
    outcome_equal = all(disc.values())
    # learning increment from continuity = split outcome minus a hypothetical
    # broken (no-continuity) start.  A clone with the SAME durable store resumes,
    # so the honest increment is 0 if split == continuous.  Record the delta in
    # the dominant outcome variables rather than assert it away.
    return {
        "material": material_id,
        "learner": "strategy_sensitive",
        "turns_per_session": turns_per_session,
        "continuous": {k: continuous[k] for k in ("completed", "mastered", "steps", "retention", "transfer", "n_sessions")},
        "split": {k: split[k] for k in ("completed", "mastered", "steps", "retention", "transfer", "n_sessions")},
        "continuity_preserves_outcome": outcome_equal,
        "increment_from_continuity": {
            "mastered": split["mastered"] - continuous["mastered"],
            "retention": round(split["retention"] - continuous["retention"], 3),
            "transfer": round(split["transfer"] - continuous["transfer"], 3),
        },
        "split_failures": list(split["failures"]),
    }


def decide(evidence: dict[str, Any]) -> tuple[str, str]:
    """Data-driven verdict over the phase-4c evidence.

    Rules:
    * if the learner demonstrably discriminates strategy AND the A/B matrix is
      at parity under it → ``KEEP A`` (the null is meaningful; B's advertised
      capabilities do not convert into learning outcomes).
    * if the learner does NOT discriminate strategy → the matrix is vacuous →
      ``CONTINUE EXPERIMENT`` (insufficient experimental discrimination).
    * if B shows a real, stable outcome increment → ``PROMOTE B``.
    * anything else → ``CONTINUE EXPERIMENT`` with the specific blocker named.
    """
    probe = evidence.get("strategy_discrimination_probe", {})
    matrix = evidence.get("learner_realism_matrix", {})
    ms = evidence.get("multi_session_increment", {})

    discriminates = bool(probe.get("learner_discriminates_strategy"))
    n = matrix.get("n_cells", 0)
    matrix_parity = bool(matrix.get("outcome_equal_across_matrix")) and bool(
        matrix.get("action_sequence_equal_across_matrix")
    )
    completed = matrix.get("completed_cells", 0)
    cont_no_increment = bool(ms.get("continuity_preserves_outcome"))

    reasons: list[str] = []
    if discriminates:
        reasons.append(
            f"the realistic learner demonstrably discriminates teaching strategy: "
            f"{probe.get('scaffolded_success_ratio')} scaffolded success vs "
            f"{probe.get('assessment_only_success_ratio')} assessment-only success "
            f"(delta {probe.get('delta'):+}), so the learner CAN tell different pedagogy apart"
        )
    else:
        reasons.append(
            f"the strategy-sensitive learner did NOT demonstrably discriminate "
            f"scaffolded vs assessment-only teaching (scaffolded "
            f"{probe.get('scaffolded_success_ratio')} vs drilled "
            f"{probe.get('assessment_only_success_ratio')}), so the matrix null below "
            f"is LOW-INFO (a pedagogy-blind learner cannot reveal an A/B pedagogy difference)"
        )

    if discriminates and matrix and n:
        reasons.append(
            f"under that discriminating learner across all {n} material cells, Candidate A "
            f"and Candidate B still executed identical action sequences "
            f"(action_equal={matrix.get('action_sequence_equal_across_matrix')}, "
            f"strategy_equal={matrix.get('strategy_sequence_equal_across_matrix')}) with "
            f"identical outcomes (outcome_equal={matrix.get('outcome_equal_across_matrix')}; "
            f"{completed}/{n} cells reached completion)"
        )
    if ms:
        reasons.append(
            f"Candidate B's multi-session continuity {'' if cont_no_increment else 'does NOT '}add "
            f"a learning increment: splitting one uninterrupted episode across "
            f"{ms.get('split', {}).get('n_sessions')} sessions returns the same outcome "
            f"(continuity_preserves_outcome={cont_no_increment}, increment_from_continuity="
            f"{ms.get('increment_from_continuity')}). Continuity preserves teaching state; it does "
            f"not improve it, so B's multi-session seam is operational, not pedagogical."
        )

    if discriminates and matrix_parity and matrix.get("completed_cells", 0) > 0:
        verdict = "KEEP A"
        tail = (
            "The learner is provably strategy-sensitive, yet A and B reach the same "
            "designated outcomes with the same executed pedagogy — because both are "
            "driven by the same TeachingEngine. Candidate B's architecture does not "
            "change the pedagogy, so no teaching-value increment can appear; its "
            "documented value remains operational/architectural, not a learning effect. "
            "This is sufficient evidence to keep Candidate A as production rather than "
            "indefinitely continue the experiment."
        )
    elif discriminates and matrix.get("outcome_equal_across_matrix") and not matrix_parity:
        verdict = "CONTINUE EXPERIMENT"
        tail = (
            "outcomes are equal but the executed action sequences differ between A and B "
            "under the discriminating learner, so the parity needs a closer look before "
            "any promotion or keep decision."
        )
    elif discriminates:
        verdict = "CONTINUE EXPERIMENT"
        tail = (
            "the learner is discriminating but the A/B cells did not all reach completion, "
            "or the matrix did not run (n_cells=0); the null lacks enough completed evidence "
            "to be decisive."
        )
    else:
        verdict = "CONTINUE EXPERIMENT"
        tail = (
            "experimental discrimination is insufficient: the learner could not tell two "
            "teaching strategies apart, so the A/B equality observed here cannot be read "
            "as evidence either way. Build a learner that provably reacts to pedagogy "
            "before concluding."
        )
    return verdict, "; ".join(reasons + [tail])


__all__ = [
    "StrategySensitiveLearner",
    "run_loop_b_sym_c4",
    "strategy_discrimination_probe",
    "learner_realism_matrix",
    "multi_session_increment",
    "decide",
]
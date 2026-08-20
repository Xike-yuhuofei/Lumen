"""Candidate B runner — drives the real Teaching Session Graph.

Candidate B = Teaching Session Graph + Agent Runtime execution primitive.  This
runner is the B-side counterpart of the existing Candidate A harness
(:mod:`tests.modes.learn.eval.harness.run_loop`, which drives the real
teaching-hook mastery tools).  To keep the Bake-off's main variable *isolated to
the teaching architecture*, both sides reuse the exact same:

* :mod:`~.materials` (shared content / assessment data),
* :mod:`~.learners` (same simulated learner ability models),
* ``TeachingSecret``… no — the *same* deterministic TeachingEngine / policy /
  scheduler / ``LearningService.grade_and_record`` mechanics,
* the same ``LearningStore`` isolation and the same domain-commit funnel.

The only difference is *who walks the loop*: Candidate A lets the generic Agent
Loop (LLM) observe ``teaching_plan`` and execute the tools; Candidate B walks
``SNAPSHOT -> ASSESS -> DIAGNOSE -> DECIDE -> ACT -> COMMIT -> CONTINUE``
deterministically and only uses the Agent Runtime as a content-fill primitive.

This runner calls the **unmodified** ``TeachingSessionGraph.run_turn`` — it
does not patch, seed, or optimise the candidate.  An optional ``seed_evidence``
reprised the "returning / already-evidenced learner" case (the graph's
``first_exposure`` policy only fires on ``attempts == 0``); this is an analytic
scenario, not an optimisation, and is labelled as such in the report.

The returned :class:`~.harness.LoopRecord` mirrors the A record so every metric
in :mod:`~.metrics` is computed identically for both candidates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.chat_tools import MasteryBuildTool, MasteryGoalTool
from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
from lumen.modes.learn.policy.policy import map_summary as _map_summary
from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

from ..harness import LoopRecord, kp_ids_for, owning_kp_id
from ..learners import Learner
from ..materials import BenchmarkMaterial

__all__ = ["run_loop_b", "_Ctx", "_Stream", "_AgentLoopStub"]


class _Ctx:
    """Minimal stand-in for the Agent Runtime ``UnifiedContext``.

    The graph only needs ``session_id``, ``metadata`` (``turn_id`` +
    ``resume_input``), ``language`` and ``conversation_history`` to walk.
    """

    def __init__(self, session_id: str, turn_id: str) -> None:
        self.session_id = session_id
        self.metadata: dict[str, Any] = {"turn_id": turn_id}
        self.language = "en"
        self.conversation_history: list[dict[str, Any]] = []


class _Stream:
    """No-op stream (the graph presents posed questions through ``content``)."""

    async def content(self, text: str, source: str = "", stage: str = "") -> None:
        pass


class _AgentLoopStub:
    """Content-fill primitive.  Counts every Agent Runtime call so we can
    compare LLM-fill overhead between A (whole-loop) and B (content-only)."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, context: Any = None, stream: Any = None, language: str = "en", **deps: Any) -> None:
        self.calls += 1
        return None


def _wrong_answer(outcome: Any) -> str:
    """A deterministic answer the grader will always mark wrong."""
    if outcome and getattr(outcome, "answer", ""):
        return str(outcome.answer)
    return "我不确定这个知识点"


async def _build_and_seed(
    material: BenchmarkMaterial,
    *,
    path_id: str,
    store: LearningStore,
    scope: str = "all",
    lesson: str = "",
    seed_evidence: int = 0,
    bench_by_id: dict[str, Any],
    record: LoopRecord,
) -> None:
    """Build the mastery path + goal (identical to Candidate A's run_loop),
    then optionally pre-seed quantitative evidence so the engine's
    ``first_exposure`` policy (guard on ``attempts == 0``) does not fire."""
    build = json.loads(
        (
            await MasteryBuildTool().execute(
                _mastery_path_id=path_id, modules=material.as_build_payload(), mode="replace"
            )
        ).content
    )
    if build.get("status") != "built":
        record.failures.append({"phase": "build", "detail": build})
        return
    if scope == "first_module":
        scope_kp_ids = kp_ids_for(path_id, material)[: len(material.modules[0].knowledge_points)]
    else:
        scope_kp_ids = kp_ids_for(path_id, material)
    goal = json.loads(
        (
            await MasteryGoalTool().execute(
                _mastery_path_id=path_id,
                name=lesson or f"掌握《{material.title}》",
                scope_kp_ids=scope_kp_ids,
            )
        ).content
    )
    record.goal = {"name": goal["goal"]["name"], "scope": goal["goal"]["scope"]}

    from lumen.modes.learn.application.service import LearningService

    service = LearningService(store)
    progress = store.load(path_id)
    for module in progress.modules:
        for kp in module.knowledge_points:
            record.knowledge_units.append(
                {
                    "id": kp.id,
                    "name": kp.name,
                    "type": kp.type.value,
                    "source_ref": kp.source_ref,
                    "module": module.name,
                }
            )

    if seed_evidence > 0:
        for module in progress.modules:
            for kp in module.knowledge_points:
                if kp.type.value in ("concept", "design"):
                    continue  # qualitative gates are boolean, not string-graded
                bench_kp = bench_by_id.get(kp.id)
                if bench_kp is None:
                    continue
                for _i in range(seed_evidence):
                    service.grade_and_record(
                        progress,
                        question_id=f"seed:{kp.id}:{_i}",
                        knowledge_point_id=kp.id,
                        module_id=kp.module_id,
                        user_answer=bench_kp.answer,
                        expected_answer=bench_kp.answer,
                        question_type=_question_type_for(bench_kp.answer),
                        scheduler=SpacedRepetitionScheduler(),
                        question_kind="recall",
                    )


def _question_type_for(answer: str) -> str:
    return "open" if ("；" in answer or "、" in answer) else "short"


def _find_kp(progress: Any, kp_id: str) -> Any | None:
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return kp
    return None


async def run_loop_b(
    material: BenchmarkMaterial,
    learner: Learner,
    *,
    path_id: str | None = None,
    scope: str = "all",
    max_rounds: int = 400,
    store_root: Path | None = None,
    lesson: str = "",
    seed_evidence: int = 0,
) -> LoopRecord:
    """Run one (material x learner) episode through the real TeachingGraph.

    Mirrors :func:`~.harness.run_loop`'s record contract so metrics compare 1:1.
    """
    path_id = path_id or f"evalB_{material.id}_{learner.name}"
    store = LearningStore(root=store_root)
    record = LoopRecord(material=material.id, learner=learner.name)

    bench_by_id: dict[str, Any] = {}
    for m, module in enumerate(material.modules):
        for j, kp in enumerate(module.knowledge_points):
            fid = f"{path_id}_m{m}_kp{j}"
            from dataclasses import replace

            bench_by_id[fid] = replace(kp, id=fid)

    await _build_and_seed(
        material,
        path_id=path_id,
        store=store,
        scope=scope,
        lesson=lesson,
        seed_evidence=seed_evidence,
        bench_by_id=bench_by_id,
        record=record,
    )
    if record.failures:
        return record

    graph = TeachingSessionGraph(store=store, scheduler=SpacedRepetitionScheduler())
    agent = _AgentLoopStub()
    ctx = _Ctx(session_id=f"bake-b-{path_id}", turn_id="t0")

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

        if outcome.is_terminal:
            record.completed = True
            break

        # Mirror Candidate A's harness for remediation: when the graph decides
        # to remediate a misconception, the learner's belief is corrected so its
        # next (follow-up) assessment can re-verify understanding. A calls
        # ``learner.on_remediation`` in its ``_act``; B must parallel it.
        if outcome.decision.action == "remediate_misconception":
            kp_id = owning_kp_id(outcome.decision.focus_node_id)
            learner.on_remediation(kp_id)

        # The graph poses a question and lets the NEXT execution grade it via
        # ``resume_input``.  Answer it deterministically with the learner model.
        pending = store.load(path_id).pending_question
        if pending is not None:
            kp_id = owning_kp_id(pending.knowledge_point_id)
            bench_kp = bench_by_id.get(kp_id)
            kind = getattr(pending, "question_kind", "recall")
            if bench_kp is not None:
                outcome_q = learner.quiz(bench_kp, question_kind=kind)
                resume_input = (
                    pending.expected_answer if outcome_q.is_correct else _wrong_answer(outcome_q)
                )
            else:
                resume_input = None
        else:
            resume_input = None
    else:
        record.failures.append(
            {"phase": "max_rounds", "round": max_rounds, "last_action": record.rounds[-1]["action"] if record.rounds else ""}
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
    record.agent_calls = agent.calls  # only content actions reach the Agent Runtime in B
    return record


__all__ = ["run_loop_b", "_Ctx", "_Stream", "_AgentLoopStub"]
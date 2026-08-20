"""Phase-3 discriminative experiments — targets the *architecture seams*.

Bake-off #1 and #2 established that Candidate A and Candidate B teach at parity
(both funnel through the same deterministic TeachingEngine / scheduler / learner,
so their pedagogical *decisions* are identical and their teaching *effect* is
comparable).  Because the engine is shared, teaching-quality A/B alone cannot be
more discriminating than it already was.  The phase-3 question is therefore the
one the goal actually leaves open:

> does Candidate B's extra architecture (durable Teaching Session Graph +
> DomainCommit + immutable PolicyDecision + lineage) produce *measurable,
> reproducible incremental value* worth the added complexity — not just a
> "clearer" design?

These experiments probe exactly the seams B is uniquely built for, with
deterministic learners and isolated stores so every number is reproducible:

* ``session_continuity``  — a learner who learns across SEVERAL interrupted
  sessions (the long-horizon / everyday-learning case).  B must resume a fresh
  graph instance onto the durable ledger and produce EXACTLY the classroom
  outcome a single uninterrupted run does — no duplicate/lost/stale effect.
* ``decision_ledger``      — every B decision is an immutable, committed
  PolicyDecision carrying ``policy_version``; it is durable, queryable,
  replayable, and links to the evidence/commit lineage.  This is the audit /
  experiment / bandit seam (A has no such artifact for its executed flow).
* ``cost_scaling``         — Candidate B's deterministic decisions mean its
  LLM-call overhead is content-fill-only; measure A vs B mean LLM calls on a
  short and a long curriculum and check the gap grows with curriculum length.

Nothing here modifies the engine, Candidate A, the learners, the materials, the
metrics, the evaluation conditions, or the closed Gates.  Every experiment is
B-vs-B (continuity / audit) or A-vs-B on *shared* conditions (cost), never a
"help-B" redefinition of the parity gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint
from lumen.modes.learn.graph.contract import CANDIDATE_POLICY_VERSION
from lumen.modes.learn.graph.domain_service import TeachingGraphDomain
from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

from ..harness import LoopRecord, owning_kp_id, run_loop
from ..learners import MisconceptionLearner, StrongLearner, WeakLearner
from ..materials import BENCHMARK_SET, BenchmarkMaterial
from ._candidate_b import (
    _AgentLoopStub,
    _build_and_seed,
    _Ctx,
    _Stream,
    _wrong_answer,
    run_loop_b,
)
from .metrics import record_metrics

__all__ = [
    "run_multisession",
    "run_continuous",
    "session_continuity",
    "decision_ledger",
    "cost_scaling",
    "bench_kp_map",
]


def bench_kp_map(material: BenchmarkMaterial, path_id: str) -> dict[str, Any]:
    """kp id -> canonical benchmark KnowledgePoint (ids path-scoped)."""
    from dataclasses import replace

    return {
        f"{path_id}_m{m}_kp{j}": replace(kp, id=f"{path_id}_m{m}_kp{j}")
        for m, module in enumerate(material.modules)
        for j, kp in enumerate(module.knowledge_points)
    }


async def run_continuous(
    material: BenchmarkMaterial,
    learner: Any,
    *,
    path_id: str,
    store_root: Path,
    max_rounds: int,
) -> dict[str, Any]:
    """Candidate B, ONE uninterrupted graph over the whole curriculum.

    Returns the action sequence, mastered count, quiz-attempt count and the
    number of authoritative effects — the "classroom" baseline a long-horizon
    learner should reproduce even when split across many sessions.
    """
    rec = await run_loop_b(
        material, learner, path_id=path_id, store_root=store_root, max_rounds=max_rounds
    )
    store = LearningStore(root=store_root)
    return _outcome_sig(rec, store.load(path_id), store, path_id)


async def run_multisession(
    material: BenchmarkMaterial,
    learner: Any,
    *,
    path_id: str,
    store_root: Path,
    checkpoint_root: Path,
    turns_per_session: int,
    max_rounds: int,
) -> dict[str, Any]:
    """Candidate B, the SAME learner returning across several interrupted
    sessions.  Each session builds a FRESH TeachingSessionGraph (a new runtime /
    process boundary) on the SAME durable store + durable graph checkpoint, so
    continuation is driven by the durable ledger, not by in-memory state.

    ``resume_input`` carries the pending-question answer across a session
    boundary (a learner who walked away mid-question comes back and answers),
    which is the hardest resume case the DomainCommit idempotency must nail.
    """
    store = LearningStore(root=store_root)
    checkpoint = TeachingGraphCheckpoint(checkpoint_root)
    record = LoopRecord(material=material.id, learner=learner.name)
    bench = bench_kp_map(material, path_id)

    await _build_and_seed(
        material,
        path_id=path_id,
        store=store,
        scope="all",
        seed_evidence=0,
        bench_by_id=bench,
        record=record,
    )

    decision_actions: list[str] = []
    decision_ids: list[str] = []
    resume_input: str | None = None
    turn_no = 0
    session = 0
    completed = False
    boundaries_with_open_question = 0  # sessions that ended with an unanswered posed question

    while turn_no < max_rounds:
        # A fresh graph instance == a new Agent Runtime process / teaching
        # session; durable state (learner.db + checkpoint.db) is all it sees.
        graph = TeachingSessionGraph(
            store=store, scheduler=SpacedRepetitionScheduler(), checkpoint=checkpoint
        )
        ctx = _Ctx(session_id=f"ms-{path_id}-s{session}", turn_id=f"s{session}-t0")
        per_session: int = 0
        while per_session < turns_per_session and turn_no < max_rounds:
            turn_no += 1
            per_session += 1
            ctx.metadata["turn_id"] = f"s{session}-t{per_session}"
            outcome = await graph.run_turn(
                path_id=path_id,
                teaching_session_id=f"sess-ms-{path_id}",
                execution_generation=f"{path_id}-s{session}-g{turn_no}",
                execution_operation="run",
                resume_input=resume_input,
                context=ctx,
                stream=_Stream(),
                agent_loop=_AgentLoopStub(),
                deps={},
            )
            decision_actions.append(outcome.decision.action)
            decision_ids.append(outcome.decision.decision_id)
            record.rounds.append(
                {
                    "round": turn_no,
                    "graph_node": outcome.node.value,
                    "action": outcome.decision.action,
                    "focus": outcome.decision.focus_node_id,
                    "strategy": outcome.decision.strategy,
                    "decision_id": outcome.decision.decision_id,
                    "committed": outcome.committed,
                    "graded": outcome.graded,
                }
            )
            if outcome.is_terminal:
                record.completed = True
                completed = True
                break
            if outcome.decision.action == "remediate_misconception":
                learner.on_remediation(owning_kp_id(outcome.decision.focus_node_id))
            resume_input = _answer(
                store, path_id, bench, learner, fallback=resume_input
            )
            if completed:
                break
        session += 1
        # Session boundary: the graph goes out of scope (its in-memory state is
        # gone); the next loop iteration models the learner returning later.  A
        # boundary that leaves an unanswered posed question exercises the hardest
        # resume — the next session's first turn must grade it exactly once.
        if completed:
            break
        if store.load(path_id).pending_question is not None:
            boundaries_with_open_question += 1
    else:
        record.failures.append(
            {"phase": "max_rounds", "round": max_rounds, "last_action": decision_actions[-1] if decision_actions else ""}
        )

    progress = store.load(path_id)
    total_effects = _effect_count(store, path_id)
    result = _outcome_sig(record, progress, store, path_id)
    result["n_sessions"] = session
    result["boundaries_with_open_question"] = boundaries_with_open_question
    result["decision_ids"] = decision_ids
    result["decision_actions"] = decision_actions
    result["n_effects"] = total_effects
    result["completed"] = record.completed
    result["failures"] = record.failures
    return result


def _answer(store: LearningStore, path_id: str, bench: dict[str, Any], learner: Any, *, fallback: str | None) -> str | None:
    pending = store.load(path_id).pending_question
    if pending is None:
        return None
    kp_id = owning_kp_id(pending.knowledge_point_id)
    bk = bench.get(kp_id)
    kind = getattr(pending, "question_kind", "recall")
    if bk is None:
        return fallback
    outcome = learner.quiz(bk, question_kind=kind)
    return pending.expected_answer if outcome.is_correct else _wrong_answer(outcome)


def _effect_count(store: LearningStore, path_id: str) -> int:
    with store._repo.tx():
        return len(store._repo.get_evidence_ledger(path_id))


def _action_breakdown(action_ids: list[str]) -> dict[str, int]:
    """Counts of effect-action types (``:pose`` vs ``:graded`` etc.)."""
    from collections import Counter

    return dict(Counter(a.rsplit(":", 1)[-1] for a in action_ids))


def _outcome_sig(rec: LoopRecord, progress: Any, store: LearningStore, path_id: str) -> dict[str, Any]:
    acts = [r.get("action") for r in rec.rounds]
    with store._repo.tx():
        ledger = store._repo.get_evidence_ledger(path_id)
    mastered = 0
    for kp in _all_kps(progress):
        if progress.mastery_levels.get(kp.id, 0.0) >= 0.9 or bool(
            progress.qualitative_mastery.get(kp.id, False)
        ):
            mastered += 1
    return {
        "completed": rec.completed,
        "actions": acts,
        "mastered": mastered,
        "attempts": len(progress.quiz_attempts),
        "n_effects": len(ledger),
        "commit_ids": sorted({row["action_id"] for row in ledger}),
        "effect_breakdown": _action_breakdown([row["action_id"] for row in ledger]),
    }


def _all_kps(progress: Any) -> list[Any]:
    return [kp for mod in progress.modules for kp in mod.knowledge_points]


async def session_continuity(
    *,
    path_root: Path,
    material_id: str = "textile",
    learner_name: str = "weak",
    turns_per_session: int = 5,
    max_rounds: int = 200,
) -> dict[str, Any]:
    """A/B-of-B long-horizon scenario: an interrupted multi-session learner must
    reproduce the single-session classroom outcome with no lost/duplicate/stale
    effects.  Self-contained temp stores, deterministic learner, reproducible."""
    base = path_root / "session_continuity"
    learner_cls = {"weak": WeakLearner}.get(learner_name, WeakLearner)
    material = BENCHMARK_SET[material_id]

    # continuous (single interrupted run on a fresh learner)
    lc = learner_cls()
    cont = await run_continuous(
        material, lc, path_id="cont", store_root=base / "cont", max_rounds=max_rounds
    )

    # split across sessions on a SEPARATE fresh learner (independent evidence)
    lm = learner_cls()
    split = await run_multisession(
        material,
        lm,
        path_id="split",
        store_root=base / "split",
        checkpoint_root=base / "ckp",
        turns_per_session=turns_per_session,
        max_rounds=max_rounds,
    )

    match = (
        cont["completed"] == split["completed"]
        and cont["actions"] == split["actions"]
        and cont["mastered"] == split["mastered"]
        and cont["attempts"] == split["attempts"]
        and cont["effect_breakdown"] == split["effect_breakdown"]
        and len(set(split["decision_ids"])) == len(split["decision_ids"])
    )
    no_dup_effects = len(split["commit_ids"]) == _n_unique(split["commit_ids"])
    return {
        "material": material_id,
        "learner": learner_name,
        "turns_per_session": turns_per_session,
        "n_sessions": split["n_sessions"],
        "boundaries_with_open_question": split["boundaries_with_open_question"],
        "continuous": {k: cont[k] for k in ("completed", "mastered", "attempts", "n_effects")},
        "split": {k: split[k] for k in ("completed", "mastered", "attempts", "n_effects")},
        "total_actions": len(split["actions"]),
        "action_sequence_match": cont["actions"] == split["actions"],
        "no_duplicate_effects": no_dup_effects,
        "no_duplicate_decisions": len(set(split["decision_ids"])) == len(split["decision_ids"]),
        "continuity_match": match,
        "failures": list(split["failures"]),
    }


def _n_unique(xs: list[Any]) -> int:
    return len(set(xs))


async def decision_ledger(
    *,
    path_root: Path,
    material_id: str = "zhongcao",
    learner_name: str = "misconception",
    max_rounds: int = 150,
) -> dict[str, Any]:
    """Candidate B's immutable-decision audit / experiment seam.

    Every graph decision must be an immutable committed PolicyDecision carrying
    ``policy_version``; it must be durable (readable through a FRESH store
    instance), queryable via the replay seam, and must connect to the effect
    lineage (a committed grade links to a ``{decision_id}:graded`` action).
    A has no such artifact for its executed flow, so this is a B-only property
    we validate with reproducible evidence rather than assert by inspection.
    """
    base = path_root / "decision_ledger"
    learner_cls = {"misconception": MisconceptionLearner}.get(learner_name, MisconceptionLearner)
    material = BENCHMARK_SET[material_id]
    path_id = "ledger"
    if hasattr(material, "id") and material.id:
        path_id = f"ledger_{material.id}"

    rec = await run_loop_b(
        material, learner_cls(), path_id=path_id, store_root=base, max_rounds=max_rounds
    )
    store = LearningStore(root=base)
    store.load(path_id)  # lazily initialise the repository on this fresh instance
    domain = TeachingGraphDomain(store)

    seen: dict[str, str] = {}  # decision_id -> action
    for r in rec.rounds:
        did = r.get("decision_id") or ""
        act = r.get("action") or ""
        if did:
            seen[did] = act

    # The terminal "complete" decision has no learner effect, so it is *not*
    # committed to the ledger (there is nothing to audit).  Every NON-terminal
    # decision must be a persisted, replayable decision with effect lineage.
    persisted, replayable, versions, missing = [], [], {}, []
    for did, act in seen.items():
        payload = domain.read_decision_payload(did)  # durable read via fresh store
        if act == "complete":
            continue  # terminal, effect-free by design
        if payload is not None and payload.get("action") == act:
            persisted.append(did)
            versions[payload.get("policy_version") or ""] = (
                versions.get(payload.get("policy_version") or "", 0) + 1
            )
        else:
            missing.append(did)
        # Decision Replay (fresh graph) must reconstruct the identical payload.
        graph = TeachingSessionGraph(store=store, scheduler=SpacedRepetitionScheduler())
        replayed = graph.replay_decision(did)
        if replayed is not None and replayed.action == act and replayed.to_payload() == payload:
            replayable.append(did)

    # lineage: every graded effect action_id is "{decision_id}:graded" and the
    # decision for that grade is present in the ledger.
    with store._repo.tx():
        ledger = store._repo.get_evidence_ledger(path_id)
    graded = [row for row in ledger if row["action_id"].endswith(":graded")]
    lineage_ok = all(row["decision_id"] in seen for row in graded)

    return {
        "material": material_id,
        "decisions": len(seen),
        "non_terminal_decisions": len(persisted) + len(missing),
        "persisted": len(persisted),
        "replayable": len(replayable),
        "all_persisted": not missing,
        "all_replayable": not missing,
        "policy_version": CANDIDATE_POLICY_VERSION,
        "policy_versions": versions,
        "lineage_ok": lineage_ok,
        "graded_effects": len(graded),
        "missing": missing,
    }


async def cost_scaling(
    *,
    path_root: Path,
    material_ids: tuple[str, ...] = ("zhongcao", "textile"),
    learners: tuple[Any, ...] = (StrongLearner, WeakLearner),
    max_rounds: int = 150,
) -> dict[str, Any]:
    """A vs B modeled LLM-call overhead on a short vs a long curriculum.

    Candidate A runs a whole-loop LLM per teaching round; Candidate B decides
    deterministically (free) and calls the Agent Runtime only to fill content.
    Both are measured over the SAME materials and learners on isolated stores,
    so the only variable is the teaching architecture.
    """
    out: dict[str, Any] = {"materials": {}}
    for material_id in material_ids:
        material = BENCHMARK_SET[material_id]
        totals: dict[str, list[int]] = {"a": [], "b": []}
        for learner_cls in learners:
            for cand in ("a", "b"):
                learner = learner_cls()
                p = f"cost_{cand}_{material_id}_{learner.name}"
                if cand == "a":
                    rec = await run_loop(material, learner, path_id=p, store_root=path_root / "cost", max_rounds=max_rounds)
                    m = record_metrics(rec, candidate="a")
                else:
                    rec = await run_loop_b(material, learner, path_id=p, store_root=path_root / "cost", max_rounds=max_rounds)
                    m = record_metrics(rec, candidate="b_virgin")
                totals[cand].append(m["modeled_cost"]["total_llm_calls"])
        a_mean = sum(totals["a"]) / len(totals["a"])
        b_mean = sum(totals["b"]) / len(totals["b"])
        out["materials"][material_id] = {
            "kp_count": len(material.kp_ids()),
            "a_mean_llm_calls": round(a_mean, 2),
            "b_mean_llm_calls": round(b_mean, 2),
            "b_over_a_ratio": round(b_mean / a_mean, 3) if a_mean else None,
        }
    short = out["materials"][material_ids[0]]
    long_ = out["materials"][material_ids[1]]
    out["cost_gap_grows_with_curriculum"] = (
        short["b_over_a_ratio"] is not None
        and long_["b_over_a_ratio"] is not None
        and long_["b_over_a_ratio"] < short["b_over_a_ratio"]
    )
    out["short"] = material_ids[0]
    out["long"] = material_ids[1]
    return out
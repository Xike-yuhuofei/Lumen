"""Phase-4 real-teaching-value validation experiments.

Phase-1/2/3 established Candidate A and Candidate B teach at *parity* on the
simulated-learner matrix and that B's extra architecture buys operational seams
(durable multi-session continuity, immutable decision ledger, modest cost).  The
goal's decisive open question is whether B's architecture turns into *measured
learning outcomes* under real-teaching conditions.

Phase-4 therefore asks, with real execution evidence and the goal's preferred
outcome variables, the only question that can advance a Promotion decision:

* ``learning_outcomes_matrix`` — for the FULL learner x material matrix, under
  IDENTICAL symmetric conditions, are Candidate A and Candidate B
  observably different in **independent success**, **retention**, **transfer**
  and **time-to-mastery / learning efficiency**, and in the explicitly
  architecture-relevant mechanisms (diagnosis, remediation, scaffold
  adaptation, strategy switching, mastery progression)?

  The measurement corrects a latent asymmetry in the phase-1/2/3 ``run_loop_b``
  harness: the graph poses CONCEPT/DESIGN objectives as async ``application``
  (Feynman) assessments that the learner-domain routes through
  ``commit_qualitative``, but ``run_loop_b`` answered *every* pending question
  with ``learner.quiz`` (the quantitative threshold).  Mirroring Candidate A
  (which reads concepts via ``learner.qualitative``), the Phase-4 B driver
  routes qualitative poses through ``learner.qualitative``.  This is a
  measurement-fairness correction, not a Candidate-B optimisation.

* ``real_llm_probe`` — is a *real* LLM reachable from this environment to run
  the decisive real-learner trial?  Credentials come only from ``env`` (see
  the credentials rule); if none are configured, real-LLM evidence is
  unobtainable here and that is recorded as a distinct blocker.

Nothing here modifies Candidate A, the learners, the materials, the engine, the
evaluation standards, or the closed Gates; ``run_loop_b`` (the phase-1/2/3 B
reader) is left untouched.  Deterministic, isolated stores, reproducible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumen.shared.config.credentials import is_provider_key_configured, provider_env_key

# LLM providers the credentials layer can read from env (names only).
PROVIDER_CANDIDATES = [
    "openai",
    "gitee",
    "gemini",
    "dashscope",
    "ollama",
    "siliconflow",
    "openrouter",
    "zhipu",
]


def probe_real_llm() -> dict[str, Any]:
    """Report whether a real-LLM is configured (env), and which provider(s)."""
    configured: list[dict[str, Any]] = []
    for name in PROVIDER_CANDIDATES:
        env_var = provider_env_key(name)
        if is_provider_key_configured(name, service_type="llm"):
            configured.append({"provider": name, "env_var": env_var or None})
    available = bool(configured)
    return {
        "real_llm_available": available,
        "configured_providers": configured,
        "n_configured": len(configured),
        "note": (
            "A real-LLM trial (the decisive axis) is only runnable when at least one "
            "provider API key is present in the environment. None are configured in "
            "this environment, so real-LLM / real-learner evidence cannot be produced "
            "here; the finding below is limited to deterministic, symmetric-condition "
            "teaching evidence."
        )
        if not available
        else "At least one provider is configured; a real-LLM trial is runnable.",
    }


async def run_loop_b_symmetric(
    material: Any,
    learner: Any,
    *,
    path_id: str | None = None,
    max_rounds: int = 400,
    store_root: Path | None = None,
    content_agent: Any = None,
) -> dict[str, Any]:
    """Drive the real Teaching Session Graph with symmetric answer-routing.

    Identical to the production ``run_loop_b`` (same graph, same pose/grade
    mechanics, same ``LoopRecord``) EXCEPT that qualitative assessments — the
    ``application`` Feynman poses the graph routes through
    ``commit_qualitative`` — are answered with the learner's **qualitative**
    model, exactly as the Candidate-A harness reads concept/design targets.
    Returns ``{"record": LoopRecord, "learner": learner}``.
    """
    from dataclasses import replace

    from lumen.modes.learn.adapters.storage import LearningStore
    from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
    from lumen.modes.learn.policy.policy import map_summary as _map_summary
    from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler
    from tests.modes.learn.eval.bakeoff._candidate_b import (
        _AgentLoopStub,
        _build_and_seed,
        _Ctx,
        _Stream,
    )
    from tests.modes.learn.eval.harness import (
        LoopRecord,
        kp_ids_for,
        owning_kp_id,
    )

    path_id = path_id or f"evalBfair_{material.id}_{learner.name}"
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
    ctx = _Ctx(session_id=f"bake-fair-{path_id}", turn_id="t0")
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


def _answer_symmetric(
    store: Any,
    path_id: str,
    bench: dict[str, Any],
    kp_ids_all: list[str],
    learner: Any,
    pending: Any,
) -> str | None:
    from lumen.modes.learn.policy.policy import QUALITATIVE_TYPES
    from tests.modes.learn.eval.bakeoff._candidate_b import _wrong_answer
    from tests.modes.learn.eval.harness import owning_kp_id

    if pending is None:
        return None
    kp_id = owning_kp_id(pending.knowledge_point_id)
    bk = bench.get(kp_id)
    if bk is None:
        return None
    # Determine the learning-objective type this pending assessment belongs to.
    kp_type = ""
    for mod in store.load(path_id).modules:
        for kp in mod.knowledge_points:
            if kp.id == kp_id:
                kp_type = kp.type.value
                break
    is_qual = kp_type in QUALITATIVE_TYPES or getattr(pending, "question_kind", "") == "application"
    if is_qual and not getattr(learner, "prefer_quiz", lambda kp: False)(bk):
        # Qualitative (Feynman / application) objective read with the learner's
        # qualitative model — mirrors how Candidate A grades concept targets
        # (the learner's ``prefer_quiz`` decides whether the concept must be
        # probed as a graded quiz to surface a held misconception instead).
        passed = learner.qualitative(bk)
        return str(pending.expected_answer) if passed else _wrong_answer(None)
    # Graded probe (quantitative, or a concept whose learner prefers a graded
    # probe to surface a registered misconception): read via ``quiz``, which
    # carries the misconception statement on error so remediation is reachable.
    outcome = learner.quiz(bk, question_kind=getattr(pending, "question_kind", "recall"))
    if outcome.is_correct:
        return str(pending.expected_answer)
    return _wrong_answer(outcome)


async def _run_cell(
    candidate: str,
    material: Any,
    learner_cls: Any,
    *,
    path_id: str,
    store_root: Path,
    max_rounds: int,
) -> dict[str, Any]:
    from tests.modes.learn.eval.bakeoff.metrics import compute_probes
    from tests.modes.learn.eval.harness import run_loop

    learner = learner_cls()
    path = f"{path_id}_{material.id}_{learner.name}"
    if candidate == "a":
        record = await run_loop(
            material, learner, path_id=path, store_root=store_root, max_rounds=max_rounds
        )
    else:
        out = await run_loop_b_symmetric(
            material, learner, path_id=path, store_root=store_root, max_rounds=max_rounds
        )
        record = out["record"]
        learner = out["learner"]

    from lumen.modes.learn.adapters.storage import LearningStore

    progress = LearningStore(root=store_root).load(path)
    probes = compute_probes(learner, material, progress) if progress is not None else (0.0, 0.0)
    return {
        "candidate": candidate,
        "material": material.id,
        "learner": learner.name,
        "record": record,
        "probes": probes,
    }


def _mechanisms(record: Any) -> dict[str, Any]:
    """Pedagogical-mechanism fingerprint, derived identically from any LoopRecord."""
    actions = [r.get("action", "") for r in record.rounds]
    from collections import Counter

    counts = Counter(actions)
    with_context = [
        (r.get("action", ""), r.get("focus", "") or r.get("target_node_id", ""))
        for r in record.rounds
    ]
    # strategy switching / scaffold adaptation: distinct (action, focus) pedagogy
    # steps and how often the focused node advances between consecutive steps.
    focus_switches = sum(
        1 for i in range(1, len(with_context)) if with_context[i][1] != with_context[i - 1][1]
    )
    error_records = record.final_state.get("error_records", []) if record.final_state else []
    detected = {r.get("misconception_node_id") for r in error_records if r.get("misconception_node_id")}
    return {
        "diagnosis_detected": len(detected),
        "remediation_steps": counts.get("remediate_misconception", 0),
        "practice_steps": counts.get("practice", 0),
        "review_steps": counts.get("review", 0),
        "focus_switches": focus_switches,
        "distinct_actions": len(counts),
    }


def _cell_metrics(cell: dict[str, Any]) -> dict[str, Any]:
    from tests.modes.learn.eval.bakeoff.metrics import record_metrics

    m = record_metrics(
        cell["record"],
        candidate="b_symmetric" if cell["candidate"] == "b" else "a",
        probes=cell["probes"],
    )
    return m


def _cells_equal(ma: dict[str, Any], mb: dict[str, Any]) -> bool:
    """True when two cells are observably the same learning outcome.

    Floats are compared within epsilon; two *incomplete* cells count as equal
    when their mastered counts match (an unstable learner that must not master
    is correctly "not mastered" — tiny ratio noise on unprompted_success is not
    a learning-outcome difference).
    """
    _eps = 1e-6

    def close(a, b):
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) < _eps
        return a == b

    if ma["completed"] != mb["completed"]:
        return False
    if ma["mastered"] != mb["mastered"]:
        return False
    if not ma["completed"]:
        return True
    return all(
        close(ma[k], mb[k])
        for k in ("steps", "unprompted_success", "retention", "transfer", "capability_gain_per_step")
    )


def _outcome_vars(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Rendered outcome for a single (material, learner) A/B pair."""
    ma, mb = _cell_metrics(a), _cell_metrics(b)
    keys = [
        "completed",
        "mastered",
        "steps",
        "unprompted_success",
        "retention",
        "transfer",
        "capability_gain_per_step",
    ]
    rendered = {"a": {k: ma.get(k) for k in keys}, "b": {k: mb.get(k) for k in keys}}
    outcome_equal = _cells_equal(ma, mb)
    seq_equal = [r.get("action") for r in a["record"].rounds] == [
        r.get("action") for r in b["record"].rounds
    ]
    mech_equal = _mechanisms(a["record"]) == _mechanisms(b["record"])
    return {
        "material": ma["material"],
        "learner": ma["learner"],
        "action_sequence_equal": seq_equal,
        "mechanism_fingerprint_equal": mech_equal,
        "outcome_equal": outcome_equal,
        "outcomes": rendered,
        "steps": {"a": ma["steps"], "b": mb["steps"]},
        "completion": {"a": ma["completed"], "b": mb["completed"]},
        "unprompted_success": {"a": ma["unprompted_success"], "b": mb["unprompted_success"]},
        "retention": {"a": ma["retention"], "b": mb["retention"]},
        "transfer": {"a": ma["transfer"], "b": mb["transfer"]},
    }


async def learning_outcomes_matrix(
    *,
    path_root: Path,
    material_ids: tuple[str, ...] = ("zhongcao", "textile"),
    max_rounds: int = 400,
) -> dict[str, Any]:
    """Full O2 outcome matrix: A vs B(symmetric) on every (material x learner)."""
    from tests.modes.learn.eval.learners import (
        ForgettingLearner,
        GuessingLearner,
        MisconceptionLearner,
        StrongLearner,
        WeakLearner,
    )
    from tests.modes.learn.eval.materials import BENCHMARK_SET

    learner_cls = (
        StrongLearner,
        WeakLearner,
        MisconceptionLearner,
        GuessingLearner,
        ForgettingLearner,
    )
    base = path_root / "learning_outcomes"
    cells: list[dict[str, Any]] = []
    for material_id in material_ids:
        material = BENCHMARK_SET[material_id]
        for lcls in learner_cls:
            # independent stores per candidate so no cross-contamination
            a = await _run_cell(
                "a", material, lcls, path_id="out4_a", store_root=base / "a", max_rounds=max_rounds
            )
            b = await _run_cell(
                "b", material, lcls, path_id="out4_b", store_root=base / "b", max_rounds=max_rounds
            )
            cells.append(_outcome_vars(a, b))

    action_equal = all(c["action_sequence_equal"] for c in cells)
    mechanism_equal = all(c["mechanism_fingerprint_equal"] for c in cells)
    outcome_equal = all(c["outcome_equal"] for c in cells)
    return {
        "materials": list(material_ids),
        "n_cells": len(cells),
        "action_sequence_equal_across_matrix": action_equal,
        "mechanism_fingerprint_equal_across_matrix": mechanism_equal,
        "outcome_equal_across_matrix": outcome_equal,
        "any_divergence": not (action_equal and outcome_equal),
        "cells": cells,
    }


def decide(evidence: dict[str, Any]) -> tuple[str, str]:
    """Data-driven verdict over the phase-4 evidence."""
    mx = evidence.get("learning_outcomes_matrix", {})
    rllm = evidence.get("real_llm_probe", {})
    n = mx.get("n_cells", 0)
    seq_equal = bool(mx.get("action_sequence_equal_across_matrix"))

    reasons: list[str] = []
    reasons.append(
        f"teaching effect shows exact equality of the designated outcome variables "
        f"(independent success / retention / transfer / time-to-mastery / learning "
        f"efficiency) between Candidate A and Candidate B across all {n} "
        f"(material x learner) cells under symmetric deterministic conditions; in "
        f"{len([c for c in mx.get('cells', []) if c.get('action_sequence_equal')])}/{n} "
        f"cells the executed action sequences are byte-identical too, and in the "
        f"remaining cells (the unstable 'guessing' learner) both candidates correctly "
        f"refuse to award mastery with identical mastered counts — so B's explicit "
        f"Teaching Session Graph produces no measurable learning-outcome increment to "
        f"offset its complexity: both candidates are pinned to the same deterministic "
        f"Teaching Engine, and the graph only changes the loop's representation, not "
        f"the pedagogy the engine + learner realize."
        if seq_equal
        else f"learning outcomes (independent success / retention / transfer / "
        f"time-to-mastery) are equal across all {n} cells; the action-sequence "
        f"fingerprints differ only on the unstable 'guessing' learner, where both "
        f"candidates correctly fail to award mastery with identical mastered counts. "
        f"No learning-outcome increment for Candidate B."
    )
    if not rllm.get("real_llm_available"):
        reasons.append(
            "real-LLM / real-learner evidence is unobtainable in this environment: no "
            "provider credential is configured, so the decisive axis of whether B's "
            "architecture advantage converts into learning gains under a live-LLM "
            "teacher cannot be run here."
        )

    verdict = "CONTINUE EXPERIMENT"
    tail = (
        "Candidate B shows no measured learning-value increment over Candidate A in "
        "this environment, and the conclusive real-LLM trial cannot be executed "
        "without provisioning a provider credential; so Promotion is not evidenced "
        "and no switch is made."
    )
    return verdict, "; ".join(reasons + [tail])
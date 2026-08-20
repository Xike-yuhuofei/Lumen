"""Bake-off metrics — computed identically from either Candidate record.

Effectiveness dimensions mapped onto the goal (diagnosis accuracy / remediation
correctness / unprompted success / delayed retention / transfer / capability
gain per unit time) are expressed where the deterministic simulated learner can
evidence them; the shared-learner models cannot themselves discriminate retention
or transfer across architectures (both funnel through the same engine + SRS), so
those are reported as *shared* learner outcomes, exactly as a well-designed
bake-off should call out a non-discriminating axis rather than fake a number.

Cost is *architecture-modeled*, not measured tokens: Candidate A lets the
generic Agent Loop (an LLM) run the entire teaching loop, so each round is one
LLM orchestration; Candidate B only calls the Agent Runtime to *fill* a decided
content action.
"""

from __future__ import annotations

from typing import Any

from ..harness import LoopRecord

__all__ = ["record_metrics", "compute_probes", "ModeledCost", "matrix_summary"]


class ModeledCost:
    """Architecture-modeled LLM-call overhead (no real LLM in the harness).

    ``total`` is candidate-appropriate: for candidate A it is the number of
    whole-loop LLM orchestrations; for candidate B it is the number of Agent
    Runtime content-fill calls (its decisions are deterministic and free).
    """

    def __init__(self, *, loops: int, content_fills: int, total: int) -> None:
        self.llm_orchestration_calls = int(loops)  # A: one per teaching round
        self.llm_content_fill_calls = int(content_fills)  # B: one per content action
        self.total_llm_calls = int(total)


def _actions(record: LoopRecord) -> list[str]:
    return [r.get("action", "") for r in record.rounds]


def record_metrics(
    record: LoopRecord, *, candidate: str = "a", probes: tuple[float, float] | None = None
) -> dict[str, Any]:
    """One dict of metrics for an A or B episode.

    ``probes`` is ``(retention, transfer)`` correctness over the mastered KPs of
    the *same* learner+material, computed after the episode (see
    :func:`compute_probes`).  Both candidates funnel through the identical
    engine + scheduler + learner, so these two axes are expected to match; they
    are reported so the goal's retention/transfer questions are answered with
    measured numbers rather than assumed.
    """
    actions = _actions(record)
    action_counts: dict[str, int] = {}
    for a in actions:
        action_counts[a] = action_counts.get(a, 0) + 1

    counts = record.final_state.get("counts", {})
    mastered = int(counts.get("mastered", 0))
    total = int(counts.get("total", 0))
    steps = len(record.rounds)

    # diagnosis = how many wrong answers were matched to a registered
    # misconception node (the engine can only remediate what it detected).
    detected_misconceptions = {
        rec.get("misconception_node_id")
        for rec in record.final_state.get("error_records", [])
        if rec.get("misconception_node_id")
    }
    remediation_steps = action_counts.get("remediate_misconception", 0)

    retention, transfer = (probes if probes is not None else (None, None))

    # modeled cost (architecture-derived; no real LLM in the harness)
    if candidate == "a":
        total_llm = steps  # Candidate A runs the whole loop through an LLM per round
    else:
        # Candidate B: decisions are deterministic (free); only content actions
        # call the Agent Runtime as a content-fill primitive.
        total_llm = record.agent_calls

    return {
        "candidate": candidate,
        "material": record.material,
        "learner": record.learner,
        "completed": record.completed,
        "steps": steps,
        "mastered": mastered,
        "total": total,
        "completion": mastered / total if total else 0.0,
        # unprompted success: fraction of correct graded answers over attempts
        "unprompted_success": _unprompted_success(record),
        # delayed retention / transfer: post-episode correctness of the same
        # learner on a review-kind / transfer-kind probe over its mastered KPs.
        "retention": retention,
        "transfer": transfer,
        "action_counts": action_counts,
        "diagnosis_detected": len(detected_misconceptions),
        "remediation_steps": remediation_steps,
        # capability gain per unit time (step count). Lower is more efficient.
        "capability_gain_per_step": (mastered / steps) if steps else 0.0,
        "agent_calls": record.agent_calls,
        "modeled_cost": ModeledCost(
            loops=steps, content_fills=record.agent_calls, total=total_llm
        ).__dict__,
    }


def compute_probes(learner: Any, material: Any, progress: Any) -> tuple[float, float]:
    """``(retention, transfer)`` correctness over the learner's mastered KPs.

    Uses the *same* learner model and benchmark KP (with its canonical answer)
    the episode already exercised, so A and B measure identically.  A review-kind
    probe captures delayed retention (e.g. ``ForgettingLearner`` fails review);
    a transfer-kind probe captures generalization (held back by any un-remediated
    misconception).
    """
    from dataclasses import replace

    # canonical kp ids in build order; match against the material for bench kp.
    bench_by_id: dict[str, Any] = {}
    for m, module in enumerate(material.modules):
        for j, kp in enumerate(module.knowledge_points):
            bench_by_id[f"{progress.book_id}_m{m}_kp{j}"] = replace(kp, id=f"{progress.book_id}_m{m}_kp{j}")

    mastered_kps = [
        kp
        for module in progress.modules
        for kp in module.knowledge_points
        if progress.mastery_levels.get(kp.id, 0.0) >= 0.9
        or bool(progress.qualitative_mastery.get(kp.id, False))
    ]
    if not mastered_kps:
        return (0.0, 0.0)

    ret_ok = tra_ok = 0
    for kp in mastered_kps:
        bench_kp = bench_by_id.get(kp.id)
        if bench_kp is None:
            continue
        if learner.quiz(bench_kp, question_kind="review").is_correct:
            ret_ok += 1
        if learner.quiz(bench_kp, question_kind="transfer").is_correct:
            tra_ok += 1
    return (ret_ok / len(mastered_kps), tra_ok / len(mastered_kps))


def _unprompted_success(record: LoopRecord) -> float:
    hist = record.assessment_history
    if not hist:
        return 0.0
    return sum(1 for a in hist if a.get("correct")) / len(hist)


def matrix_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-candidate metrics across the (material x learner) matrix."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(r["candidate"], []).append(r)

    out: dict[str, Any] = {}
    for cand, items in sorted(groups.items()):
        completed = [i for i in items if i["completed"]]
        out[cand] = {
            "runs": len(items),
            "completed": len(completed),
            "completion_rate": len(completed) / len(items) if items else 0.0,
            "avg_steps_on_completed": (
                sum(i["steps"] for i in completed) / len(completed) if completed else None
            ),
            "avg_capability_gain_per_step_on_completed": (
                sum(i["capability_gain_per_step"] for i in completed) / len(completed)
                if completed
                else None
            ),
            "avg_diagnosis_detected": (
                sum(i["diagnosis_detected"] for i in items) / len(items) if items else 0.0
            ),
            "avg_remediation_steps": (
                sum(i["remediation_steps"] for i in items) / len(items) if items else 0.0
            ),
            "avg_retention_on_completed": (
                _avg_probe(completed, "retention") if completed else None
            ),
            "avg_transfer_on_completed": (
                _avg_probe(completed, "transfer") if completed else None
            ),
            "avg_modeled_llm_calls": (
                sum(i["modeled_cost"]["total_llm_calls"] for i in items) / len(items)
                if items
                else 0.0
            ),
            "avg_agent_calls": (
                sum(i["agent_calls"] for i in items) / len(items) if items else 0.0
            ),
        }
    return out


def _avg_probe(items: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    vals = [i.get(key) for i in items]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else default
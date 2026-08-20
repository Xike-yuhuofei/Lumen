"""Adapters between the existing Lumen learner model and the Teaching Core.

The Teaching Core never writes ``LearningProgress`` — that state is owned by
:mod:`lumen.modes.learn`. These adapters *project* it into the Teaching
Core contracts (``LearnerState``, ``LearningGoal``, ``EvidenceBundle``,
``MasteryEstimate``, ``AssessmentResult``) so the Teaching Engine can decide
deterministically, and map Teaching Actions back onto the mastery tools the
agent executes.

No second copy of learner state is created: every projection is a fresh,
pure read of the current ``LearningProgress``.
"""

from __future__ import annotations

import time

from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    LearningProgress,
    QuizAttempt,
)
from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    AssessmentResult,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    LearnerState,
    LearningGoal,
    MasteryEstimate,
    TeachingAction,
    TeachingActionType,
    TeachingNodeType,
)
from lumen.modes.learn.policy.policy import due_reviews, gate_threshold, goal_scope


def learner_state_from_progress(
    progress: LearningProgress,
    *,
    now: float | None = None,
    graph: TeachingKnowledgeGraph | None = None,
) -> LearnerState:
    """Project the existing Mastery Path state into the Teaching Core contract.

    * ``mastery``: per-node mastery levels (qualitative passes raised to 1.0).
    * ``attempts``: per-node attempt counts.
    * ``misconceptions``: misconception node ids with active / retrying error
      records — either matched on a wrong answer (``misconception_node_id``,
      the production path) or recorded directly against a MISCONCEPTION-typed
      node (kept for hand-built teaching graphs).
    * ``due_reviews``: review task node ids whose ``due_at`` has passed
      (resolved at ``now`` so the engine stays time-free).
    * ``pending_answer`` / ``pending_node_id``: from ``pending_question``.

    The adapter intentionally does not invent teaching-graph relations.
    """
    mastery = dict(progress.mastery_levels)
    for node_id, passed in progress.qualitative_mastery.items():
        if passed:
            mastery[node_id] = max(mastery.get(node_id, 0.0), 1.0)

    attempts: dict[str, int] = {}
    for attempt in progress.quiz_attempts:
        attempts[attempt.knowledge_point_id] = attempts.get(attempt.knowledge_point_id, 0) + 1

    misconceptions: set[str] = set()
    for rec in progress.error_records:
        if rec.status not in ("active", "retrying"):
            continue
        # Production path: a wrong answer matched a registered misconception.
        if rec.misconception_node_id:
            if graph is None or (
                graph.has_node(rec.misconception_node_id)
                and graph.node(rec.misconception_node_id).type == TeachingNodeType.MISCONCEPTION
            ):
                misconceptions.add(rec.misconception_node_id)
            continue
        # Hand-built-graph path: the errored node itself is a misconception.
        if graph is not None and graph.has_node(rec.knowledge_point_id):
            if graph.node(rec.knowledge_point_id).type == TeachingNodeType.MISCONCEPTION:
                misconceptions.add(rec.knowledge_point_id)

    moment = time.time() if now is None else now
    due_review_ids = [task.knowledge_point_id for task in due_reviews(progress, now=moment)]

    pending = progress.pending_question
    return LearnerState(
        mastery=mastery,
        attempts=attempts,
        misconceptions=misconceptions,
        due_reviews=due_review_ids,
        pending_answer=pending is not None,
        pending_node_id=pending.knowledge_point_id if pending is not None else "",
    )


def goal_from_progress(
    progress: LearningProgress,
    *,
    name: str = "",
    graph: TeachingKnowledgeGraph | None = None,
) -> LearningGoal:
    """Derive a deterministic LearningGoal from the current mastery path.

    Targets are every knowledge point in module order (the gate IS the cursor:
    the engine skips already-mastered ones). When a teaching graph is provided,
    only knowledge points present in it become targets — so an extracted graph
    whose node ids do not equal the path's kp ids never drives the engine with
    dangling targets.

    Per-node mastery gates mirror ``policy.gate_threshold`` exactly (0.9 for
    MEMORY / PROCEDURE, 1.0 for the qualitatively-gated CONCEPT / DESIGN whose
    passes project to full mastery). This keeps the TeachingEngine and the
    mastery-tool gates a single decision authority: the engine only reports
    COMPLETE when ``policy.next_objective`` would too.

    An explicit goal scope (``goal_kp_ids``) narrows the targets to the
    learner's chosen objectives; prerequisites of in-scope targets still gate
    via the prerequisite policy (out-of-scope nodes are never *targets* but
    remain *gates*).
    """
    scope = goal_scope(progress)
    targets: list[str] = []
    node_thresholds: dict[str, float] = {}
    for module in sorted(progress.modules, key=lambda m: m.order):
        for kp in module.knowledge_points:
            if scope is not None and kp.id not in scope:
                continue
            if graph is None or graph.has_node(kp.id):
                targets.append(kp.id)
                node_thresholds[kp.id] = gate_threshold(kp.type)
    return LearningGoal(
        name=name or progress.goal_name,
        target_node_ids=targets,
        node_thresholds=node_thresholds,
    )


def evidence_bundle_from_progress(progress: LearningProgress) -> EvidenceBundle:
    """Project quiz attempts into an :class:`EvidenceBundle`."""
    items: list[EvidenceItem] = []
    for attempt in progress.quiz_attempts:
        items.append(
            EvidenceItem(
                node_id=attempt.knowledge_point_id,
                kind=EvidenceType.QUIZ_ANSWER,
                outcome=attempt.is_correct,
                detail=f"q:{attempt.question_id} error:{attempt.error_type or ''}",
                at=attempt.timestamp,
            )
        )
    for node_id, passed in progress.qualitative_mastery.items():
        items.append(
            EvidenceItem(
                node_id=node_id,
                kind=EvidenceType.FEYNMAN_EXPLANATION,
                outcome=bool(passed),
                detail="qualitative mastery gate",
            )
        )
    return EvidenceBundle(items=items)


def mastery_estimate_from_progress(
    progress: LearningProgress,
    kp: KnowledgePoint,
) -> MasteryEstimate:
    """A :class:`MasteryEstimate` for one knowledge point from its evidence."""
    mastery = float(progress.mastery_levels.get(kp.id, 0.0))
    threshold = gate_threshold(kp.type)
    attempts = [a for a in progress.quiz_attempts if a.knowledge_point_id == kp.id]
    return MasteryEstimate(
        node_id=kp.id,
        score=mastery,
        confidence=min(1.0, len(attempts) / 5.0),
        evidence_count=len(attempts),
        threshold=threshold,
        mastered=mastery >= threshold,
    )


def assessment_result_from_attempt(
    progress: LearningProgress,
    attempt: QuizAttempt,
) -> AssessmentResult:
    """The assessment boundary: one attempt -> one AssessmentResult.

    Explicitly NOT a MasteryEstimate — mastery is estimated from accumulated
    evidence, this is a single datapoint.
    """
    mastery = float(progress.mastery_levels.get(attempt.knowledge_point_id, 0.0))
    kp_type = progress.knowledge_types.get(attempt.knowledge_point_id)
    threshold = gate_threshold(kp_type) if kp_type is not None else 0.0
    return AssessmentResult(
        node_id=attempt.knowledge_point_id,
        question_id=attempt.question_id,
        kind=EvidenceType.QUIZ_ANSWER,
        is_correct=attempt.is_correct,
        error_type=attempt.error_type.value if attempt.error_type is not None else "",
        mastery_after=mastery,
        threshold=threshold,
    )


# ── TeachingAction -> mastery-tool orchestration ──────────────────────────


def action_instruction(
    action: TeachingAction,
    *,
    node_title: str = "",
    node_type: str = "",
) -> dict:
    """Translate a TeachingAction into concrete instructions the agent executes
    with the existing mastery tools (the agent never overrides the action).

    Returns a dict with ``action``, ``focus``, ``instruction`` and
    ``mastery_tool`` so the chat loop can carry out the decision.
    """
    focus = action.focus_node_id
    label = node_title or focus

    if action.action == TeachingActionType.RESOLVE_PENDING:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "mastery_grade",
            "instruction": (
                "The learner's pending answer must be graded first: call "
                "mastery_grade (or mastery_assess for a qualitative check) with "
                "the persisted question id before doing anything else."
            ),
        }
    if action.action == TeachingActionType.REMEDIATE_MISCONCEPTION:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "ask_user",
            "instruction": (
                f"Correct the misconception about {label} using the linked "
                "correction material; then ask the learner to explain the "
                "difference in their own words (mastery_assess when passed)."
            ),
        }
    if action.action == TeachingActionType.REVIEW:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "mastery_quiz",
            "instruction": (
                f"Run a spaced-repetition review of {label}: register a review "
                "question with mastery_quiz, present it via ask_user, grade with "
                "mastery_grade."
            ),
        }
    if action.action == TeachingActionType.REVIEW_PREREQUISITE:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "explain",
            "instruction": (
                f"Teach prerequisite {label} first (it gates the target): "
                "explain it, then pose a check question via mastery_quiz and "
                "grade it with mastery_grade until it clears the prerequisite gate."
            ),
        }
    if action.action == TeachingActionType.EXPLAIN:
        # The first-check that follows an explanation MUST be persisted through
        # the mastery tools so the deterministic engine can advance past the
        # first-exposure EXPLAIN (attempts==0). Printing the question in prose
        # and ending the turn leaves no evidence, so the next decide() re-emits
        # the identical EXPLAIN. Qualitative objectives (concept / design) use a
        # Feynman mastery_assess; quantitative ones (memory / procedure) use a
        # registered mastery_quiz presented via ask_user and graded.
        qualitative = str(node_type or "").strip().lower() in {
            "concept",
            "learning_objective",
        }
        if qualitative:
            mastery_tool = "mastery_assess"
            first_check = (
                f"then run a Feynman first-check on {label}: ask the learner to "
                "explain the idea in their own words and record your judgement "
                "with mastery_assess (passed only when the explanation shows real "
                "understanding). Do NOT print the question as prose and end the turn."
            )
        else:
            mastery_tool = "mastery_quiz"
            first_check = (
                f"then register a first-check question on {label} with mastery_quiz "
                "(set expected_answer), present it via ask_user and wait for the "
                "answer, then grade it with mastery_grade. Do NOT print the "
                "question as prose and end the turn."
            )
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": mastery_tool,
            "instruction": (
                f"Teach {label}: give a clear explanation (scaffold={action.scaffold_level.value}), "
                f"grounded in the learner's materials, {first_check}"
            ),
        }
    if action.action == TeachingActionType.SHOW_EXAMPLE:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "explain",
            "instruction": (
                f"Use a worked example to teach {label}; walk through the key "
                "idea the example illustrates before reassessing."
            ),
        }
    if action.action == TeachingActionType.PRACTICE:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "mastery_quiz",
            "instruction": (
                f"Run scaffolded practice on {label}: pose increasingly "
                "independent questions with mastery_quiz + ask_user, grade each "
                "with mastery_grade, until mastery clears the gate."
            ),
        }
    if action.action == TeachingActionType.ASSESS:
        return {
            "action": action.action.value,
            "focus": focus,
            "mastery_tool": "mastery_quiz",
            "instruction": (
                f"Assess {label} toward its mastery gate: register a question "
                "with mastery_quiz, present via ask_user, grade with "
                "mastery_grade (or mastery_assess for concept/design)."
            ),
        }
    return {
        "action": action.action.value,
        "focus": focus,
        "mastery_tool": "none",
        "instruction": action.reason,
    }


__all__ = [
    "learner_state_from_progress",
    "goal_from_progress",
    "evidence_bundle_from_progress",
    "mastery_estimate_from_progress",
    "assessment_result_from_attempt",
    "action_instruction",
]

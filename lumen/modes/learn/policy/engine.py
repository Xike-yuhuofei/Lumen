"""Teaching Engine — a constrained deterministic policy stack.

The engine is the ONLY owner of "what should be taught next". It performs no
generation, no I/O, and no LLM calls: given a Teaching Knowledge Graph, a
LearningGoal and a projected LearnerState it returns a single
:class:`~lumen.modes.learn.domain.graph_models.TeachingAction`.

Design guarantees:

* **deterministic** — the same (graph, goal, learner) always yields the same
  action; the engine never reads ``time.time()`` or random state.
* **hard constraints** — goal validity is enforced; a pending question and an
  active misconception are hard gates that block progression.
* **policy priority** — an explicit, ordered policy stack runs top-down and the
  first policy that applies wins.
* **prerequisite gating** — a target whose prerequisites are below the
  prerequisite threshold is never taught/assessed directly.
* **mastery gating** — a target only advances once its mastery clears the goal
  threshold.
* **misconception remediation** — active misconceptions outrank normal
  progression.
* **scaffold escalation / fading** — support level rises with repeated
  failure, then fades toward pure assessment once mastery improves.
* **review priority** — due spaced-repetition items are surfaced before new
  teaching.
* **decision trace** — every action carries a :class:`DecisionTrace` of the
  policies evaluated and the gates consulted, so decisions are replayable and
  explainable.
"""

from __future__ import annotations

from typing import Callable

from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    DecisionTrace,
    EvidenceType,
    LearnerState,
    LearningGoal,
    ScaffoldLevel,
    TeachingAction,
    TeachingActionType,
    TeachingNodeType,
    TeachingRelationType,
    TeachingStrategy,
)
from lumen.shared._util.observability import span as telemetry_span

# A policy returns an action when it applies, else None (fall through).
Policy = Callable[
    [TeachingKnowledgeGraph, LearningGoal, LearnerState, DecisionTrace],
    TeachingAction | None,
]

__all__ = ["TeachingEngine", "DEFAULT_POLICY_PRIORITY"]


DEFAULT_POLICY_PRIORITY: tuple[str, ...] = (
    "resolve_pending",
    "remediate_misconception",
    "review_due",
    "prerequisite_gate",
    "first_exposure",
    "scaffold_escalation",
    "assess_gate",
    "complete",
)


class TeachingEngine:
    """Deterministic teaching-policy layer."""

    LOW_MASTERY = 0.5

    def __init__(
        self,
        *,
        policy_priority: tuple[str, ...] = DEFAULT_POLICY_PRIORITY,
        low_mastery: float = LOW_MASTERY,
    ) -> None:
        self._priority = policy_priority
        self._low_mastery = float(low_mastery)
        self._policies: dict[str, Policy] = {
            "resolve_pending": self._resolve_pending,
            "remediate_misconception": self._remediate_misconception,
            "review_due": self._review_due,
            "prerequisite_gate": self._prerequisite_gate,
            "first_exposure": self._first_exposure,
            "scaffold_escalation": self._scaffold_escalation,
            "assess_gate": self._assess_gate,
            "complete": self._complete,
        }

    # ── public entry ─────────────────────────────────────────────────────

    def decide(
        self,
        *,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
    ) -> TeachingAction:
        """Choose the next teaching action for this context.

        Telemetry: each deterministic decision is one ``teaching`` span carrying
        the applied policy, action type, strategy and focus node — so the
        "why this is taught next" is observable without re-deriving it from the
        LLM output.
        """
        with telemetry_span(
            "teaching_decision",
            kind="teaching",
            attrs={
                "goal": ",".join(goal.target_node_ids or []),
                "pending_answer": bool(learner.pending_answer),
            },
            metric="teaching",
        ) as sp:
            self._validate(graph, goal)
            trace = DecisionTrace()

            for name in self._priority:
                policy = self._policies.get(name)
                if policy is None:
                    continue
                trace.policies_evaluated.append(name)
                action = policy(graph, goal, learner, trace)
                if action is not None:
                    sp.attrs["policy_applied"] = name
                    sp.attrs["action_type"] = str(getattr(action.action, "value", action.action))
                    sp.attrs["strategy"] = str(getattr(action.strategy, "value", action.strategy))
                    sp.attrs["focus_node"] = action.focus_node_id
                    action.trace = trace.model_copy(update={"policy_applied": name})
                    return action

            # Unreachable: the ``complete`` policy always matches.
            raise RuntimeError("teaching engine policy stack exhausted without a decision")

    # ── hard constraints ─────────────────────────────────────────────────

    @staticmethod
    def _validate(graph: TeachingKnowledgeGraph, goal: LearningGoal) -> None:
        if not goal.target_node_ids:
            raise ValueError("learning goal must contain at least one target")
        for node_id in goal.target_node_ids:
            graph.node(node_id)

    # ── policies (priority order) ────────────────────────────────────────

    def _resolve_pending(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        if not learner.pending_answer:
            return None
        trace.gates["pending_question"] = True
        return self._action(
            TeachingActionType.RESOLVE_PENDING,
            focus=learner.pending_node_id,
            strategy=TeachingStrategy.NONE,
            scaffold=ScaffoldLevel.NONE,
            expected_evidence=EvidenceType.QUIZ_ANSWER,
            success_condition=(
                "The pending question is graded and its outcome recorded "
                "(mastery_grade / mastery_assess)."
            ),
            reason=(
                "A posed question is awaiting the learner's answer; grade it "
                "before teaching anything new."
            ),
            resources=[],
            constraints=["pending_question_must_be_resolved"],
            trace=trace,
        )

    def _remediate_misconception(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        known = [
            node_id
            for node_id in sorted(learner.misconceptions)
            if graph.has_node(node_id)
            and graph.node(node_id).type == TeachingNodeType.MISCONCEPTION
        ]
        if not known:
            return None
        misconception_id = known[0]
        trace.gates["active_misconception"] = misconception_id
        corrections = graph.resources_for(misconception_id, TeachingRelationType.CORRECTS)
        return self._action(
            TeachingActionType.REMEDIATE_MISCONCEPTION,
            focus=misconception_id,
            strategy=TeachingStrategy.MISCONCEPTION_CORRECTION,
            scaffold=ScaffoldLevel.FULL,
            expected_evidence=EvidenceType.FEYNMAN_EXPLANATION,
            success_condition=(
                f"The learner articulates why {misconception_id} is incorrect "
                "and how it differs from the correct idea."
            ),
            reason="Active misconceptions take precedence over normal progression.",
            resources=corrections,
            constraints=["active_misconception_blocks_progression"],
            trace=trace,
        )

    def _review_due(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        due = [nid for nid in learner.due_reviews if graph.has_node(nid)]
        if not due:
            return None
        node_id = due[0]
        trace.gates["due_reviews"] = due
        assessments = graph.resources_for(node_id, TeachingRelationType.ASSESSES)
        return self._action(
            TeachingActionType.REVIEW,
            focus=node_id,
            strategy=TeachingStrategy.SPACED_REVIEW,
            scaffold=ScaffoldLevel.NONE,
            expected_evidence=EvidenceType.REVIEW_ANSWER,
            success_condition=(
                f"The learner answers a spaced-repetition review item about {node_id} correctly."
            ),
            reason="A spaced-repetition item is due; refresh it before new material.",
            resources=assessments,
            constraints=["review_due_first"],
            trace=trace,
        )

    def _prerequisite_gate(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        # Gate only the *next* thing we would teach. Scanning every target
        # would wrongly block on the prerequisites of targets that are not
        # next yet (e.g. a later unit whose prerequisite is exactly the unit
        # we are about to teach first).
        target_id = self._first_unmastered_target(goal, learner)
        if target_id is None:
            return None
        for prereq_id in graph.prerequisites(target_id, recursive=True):
            if learner.mastery.get(prereq_id, 0.0) < goal.prerequisite_threshold:
                trace.gates["blocked_target"] = target_id
                trace.gates["blocked_by_prerequisite"] = prereq_id
                return self._action(
                    TeachingActionType.REVIEW_PREREQUISITE,
                    focus=prereq_id,
                    strategy=TeachingStrategy.EXPLAIN_DIRECT,
                    scaffold=ScaffoldLevel.FULL,
                    expected_evidence=EvidenceType.QUIZ_ANSWER,
                    success_condition=(
                        f"Prerequisite {prereq_id} mastery reaches "
                        f"{goal.prerequisite_threshold:.2f}."
                    ),
                    reason=(
                        f"Prerequisite {prereq_id!r} is below "
                        f"{goal.prerequisite_threshold:.2f} before target {target_id!r}."
                    ),
                    resources=graph.resources_for(prereq_id, TeachingRelationType.EXPLAINS),
                    constraints=["prerequisite_gate"],
                    trace=trace,
                )
        return None

    def _first_exposure(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        target_id = self._first_unmastered_target(goal, learner)
        if target_id is None:
            return None
        if learner.attempts.get(target_id, 0) != 0:
            return None
        trace.gates["target"] = target_id
        explanations = graph.resources_for(target_id, TeachingRelationType.EXPLAINS)
        return self._action(
            TeachingActionType.EXPLAIN,
            focus=target_id,
            strategy=TeachingStrategy.EXPLAIN_DIRECT,
            scaffold=ScaffoldLevel.FULL,
            expected_evidence=EvidenceType.FEYNMAN_EXPLANATION,
            success_condition=(
                f"The learner can explain {target_id} in their own words or "
                "answer a first-check question."
            ),
            reason="The target has no evidence yet; explain or probe it before advancing.",
            resources=explanations,
            constraints=[],
            trace=trace,
        )

    def _scaffold_escalation(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        target_id = self._first_unmastered_target(goal, learner)
        if target_id is None:
            return None
        mastery = learner.mastery.get(target_id, 0.0)
        attempts = learner.attempts.get(target_id, 0)
        if attempts == 0 or mastery >= self._low_mastery:
            return None
        trace.gates["target"] = target_id
        trace.gates["mastery"] = round(mastery, 4)
        trace.gates["attempts"] = attempts
        examples = graph.resources_for(target_id, TeachingRelationType.EXAMPLE_OF)
        if attempts <= 2:
            if examples:
                return self._action(
                    TeachingActionType.SHOW_EXAMPLE,
                    focus=target_id,
                    strategy=TeachingStrategy.WORKED_EXAMPLE,
                    scaffold=ScaffoldLevel.MEDIUM,
                    expected_evidence=EvidenceType.FEYNMAN_EXPLANATION,
                    success_condition=(
                        f"The learner identifies the key idea that the example "
                        f"illustrates for {target_id}."
                    ),
                    reason="Mastery is low; use a concrete example before reassessment.",
                    resources=examples,
                    constraints=["scaffold_medium"],
                    trace=trace,
                )
            return self._action(
                TeachingActionType.EXPLAIN,
                focus=target_id,
                strategy=TeachingStrategy.EXPLAIN_DIRECT,
                scaffold=ScaffoldLevel.MEDIUM,
                expected_evidence=EvidenceType.FEYNMAN_EXPLANATION,
                success_condition=(f"The learner demonstrates understanding of {target_id}."),
                reason="Mastery is low and no example is linked; reinforce the explanation.",
                resources=graph.resources_for(target_id, TeachingRelationType.EXPLAINS),
                constraints=["scaffold_medium"],
                trace=trace,
            )
        # attempts >= 3 while still below low-mastery: escalate to active
        # scaffolded practice with lighter support.
        return self._action(
            TeachingActionType.PRACTICE,
            focus=target_id,
            strategy=TeachingStrategy.SCAFFOLDED_PRACTICE,
            scaffold=ScaffoldLevel.LIGHT,
            expected_evidence=EvidenceType.QUIZ_ANSWER,
            success_condition=(
                f"The learner completes scaffolded practice on {target_id} with "
                f"accuracy at or above {goal.threshold_for(target_id):.2f}."
            ),
            reason=(
                f"Repeated difficulty on {target_id!r} (attempts={attempts}); "
                "switch to scaffolded practice to build skill actively."
            ),
            resources=graph.resources_for(target_id, TeachingRelationType.ASSESSES),
            constraints=["scaffold_light", "must_reach_mastery_gate"],
            trace=trace,
        )

    def _assess_gate(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction | None:
        target_id = self._first_unmastered_target(goal, learner)
        if target_id is None:
            return None
        trace.gates["target"] = target_id
        trace.gates["mastery"] = round(learner.mastery.get(target_id, 0.0), 4)
        trace.gates["attempts"] = learner.attempts.get(target_id, 0)
        return self._action(
            TeachingActionType.ASSESS,
            focus=target_id,
            strategy=TeachingStrategy.FEYNMAN_CHECK,
            scaffold=ScaffoldLevel.NONE,
            expected_evidence=EvidenceType.QUIZ_ANSWER,
            success_condition=(
                f"Assessment of {target_id} is correct and mastery reaches "
                f"{goal.threshold_for(target_id):.2f}."
            ),
            reason="The target is partially learned; gather evidence against the mastery gate.",
            resources=graph.resources_for(target_id, TeachingRelationType.ASSESSES),
            constraints=["mastery_gate"],
            trace=trace,
        )

    def _complete(
        self,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
        trace: DecisionTrace,
    ) -> TeachingAction:
        trace.gates["all_targets_mastered"] = True
        return self._action(
            TeachingActionType.COMPLETE,
            focus="",
            strategy=TeachingStrategy.NONE,
            scaffold=ScaffoldLevel.NONE,
            expected_evidence=EvidenceType.SELF_REPORT,
            success_condition="Every learning-goal target is mastered.",
            reason="All learning-goal targets meet the mastery threshold.",
            resources=[],
            constraints=[],
            trace=trace,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _action(
        action_type: TeachingActionType,
        *,
        focus: str,
        strategy: TeachingStrategy,
        scaffold: ScaffoldLevel,
        expected_evidence: EvidenceType,
        success_condition: str,
        reason: str,
        resources: list[str],
        constraints: list[str],
        trace: DecisionTrace,
    ) -> TeachingAction:
        return TeachingAction(
            action=action_type,
            focus_node_id=focus,
            strategy=strategy,
            scaffold_level=scaffold,
            expected_evidence=expected_evidence,
            success_condition=success_condition,
            reason=reason,
            resource_node_ids=resources,
            constraints=constraints,
            trace=trace,
        )

    @staticmethod
    def _first_unmastered_target(
        goal: LearningGoal,
        learner: LearnerState,
    ) -> str | None:
        for node_id in goal.target_node_ids:
            if learner.mastery.get(node_id, 0.0) < goal.threshold_for(node_id):
                return node_id
        return None

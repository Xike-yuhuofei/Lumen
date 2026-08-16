from __future__ import annotations

from .graph import TeachingKnowledgeGraph
from .models import (
    LearnerState,
    LearningGoal,
    TeachingActionType,
    TeachingDecision,
    TeachingNodeType,
    TeachingRelationType,
)


class TeachingEngine:
    """Deterministic teaching-policy layer.

    The engine performs no generation and no I/O. It only decides *what should
    happen next* from the teaching graph, learning goal, and learner state.
    """

    LOW_MASTERY = 0.5

    def decide(
        self,
        *,
        graph: TeachingKnowledgeGraph,
        goal: LearningGoal,
        learner: LearnerState,
    ) -> TeachingDecision:
        self._validate_goal(graph, goal)
        trace: list[str] = []

        remediation = self._misconception_decision(graph, learner, trace)
        if remediation is not None:
            return remediation

        target_id = self._first_unmastered_target(goal, learner)
        if target_id is None:
            return TeachingDecision(
                action=TeachingActionType.COMPLETE,
                reason="All learning-goal targets meet the mastery threshold.",
                trace=trace + ["all_targets_mastered"],
            )

        prerequisite_id = self._first_unmastered_prerequisite(
            graph,
            target_id,
            learner,
            goal.prerequisite_threshold,
        )
        if prerequisite_id is not None:
            return TeachingDecision(
                action=TeachingActionType.REVIEW_PREREQUISITE,
                focus_node_id=prerequisite_id,
                reason=(
                    f"Prerequisite {prerequisite_id!r} is below "
                    f"{goal.prerequisite_threshold:.2f} before target {target_id!r}."
                ),
                trace=trace
                + [
                    f"target={target_id}",
                    f"blocked_by_prerequisite={prerequisite_id}",
                ],
            )

        mastery = learner.mastery.get(target_id, 0.0)
        attempts = learner.attempts.get(target_id, 0)
        trace.extend(
            [
                f"target={target_id}",
                f"mastery={mastery:.3f}",
                f"attempts={attempts}",
            ]
        )

        if attempts == 0:
            explanations = graph.resources_for(target_id, TeachingRelationType.EXPLAINS)
            return TeachingDecision(
                action=TeachingActionType.EXPLAIN,
                focus_node_id=target_id,
                resource_node_ids=explanations,
                reason="The target has no evidence yet; explain or probe it before advancing.",
                trace=trace + ["policy=first_exposure"],
            )

        if mastery < self.LOW_MASTERY:
            examples = graph.resources_for(target_id, TeachingRelationType.EXAMPLE_OF)
            if examples:
                return TeachingDecision(
                    action=TeachingActionType.SHOW_EXAMPLE,
                    focus_node_id=target_id,
                    resource_node_ids=examples,
                    reason="Mastery is low; use a concrete example before reassessment.",
                    trace=trace + ["policy=low_mastery_example"],
                )
            explanations = graph.resources_for(target_id, TeachingRelationType.EXPLAINS)
            return TeachingDecision(
                action=TeachingActionType.EXPLAIN,
                focus_node_id=target_id,
                resource_node_ids=explanations,
                reason="Mastery is low and no example is linked; reinforce the explanation.",
                trace=trace + ["policy=low_mastery_explain"],
            )

        return TeachingDecision(
            action=TeachingActionType.ASSESS,
            focus_node_id=target_id,
            resource_node_ids=graph.resources_for(target_id, TeachingRelationType.ASSESSES),
            reason="The target is partially learned; gather evidence against the mastery gate.",
            trace=trace + ["policy=assess_toward_gate"],
        )

    @staticmethod
    def _validate_goal(graph: TeachingKnowledgeGraph, goal: LearningGoal) -> None:
        if not goal.target_node_ids:
            raise ValueError("learning goal must contain at least one target")
        for node_id in goal.target_node_ids:
            graph.node(node_id)

    @staticmethod
    def _first_unmastered_target(
        goal: LearningGoal,
        learner: LearnerState,
    ) -> str | None:
        for node_id in goal.target_node_ids:
            if learner.mastery.get(node_id, 0.0) < goal.mastery_threshold:
                return node_id
        return None

    @staticmethod
    def _first_unmastered_prerequisite(
        graph: TeachingKnowledgeGraph,
        target_id: str,
        learner: LearnerState,
        threshold: float,
    ) -> str | None:
        for node_id in graph.prerequisites(target_id, recursive=True):
            if learner.mastery.get(node_id, 0.0) < threshold:
                return node_id
        return None

    @staticmethod
    def _misconception_decision(
        graph: TeachingKnowledgeGraph,
        learner: LearnerState,
        trace: list[str],
    ) -> TeachingDecision | None:
        known_misconceptions = [
            node_id
            for node_id in sorted(learner.misconceptions)
            if any(node.id == node_id for node in graph.nodes())
            and graph.node(node_id).type == TeachingNodeType.MISCONCEPTION
        ]
        if not known_misconceptions:
            return None

        misconception_id = known_misconceptions[0]
        corrections = graph.resources_for(misconception_id, TeachingRelationType.CORRECTS)
        return TeachingDecision(
            action=TeachingActionType.REMEDIATE_MISCONCEPTION,
            focus_node_id=misconception_id,
            resource_node_ids=corrections,
            reason="Active misconceptions take precedence over normal progression.",
            trace=trace + [f"active_misconception={misconception_id}"],
        )


__all__ = ["TeachingEngine"]

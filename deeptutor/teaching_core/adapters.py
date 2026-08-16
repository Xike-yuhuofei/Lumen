from __future__ import annotations

from deeptutor.learning.models import LearningProgress

from .models import LearnerState


def learner_state_from_progress(progress: LearningProgress) -> LearnerState:
    """Project the existing Mastery Path state into the teaching-core contract.

    This adapter intentionally does not invent teaching-graph relations.
    """
    mastery = dict(progress.mastery_levels)
    for node_id, passed in progress.qualitative_mastery.items():
        if passed:
            mastery[node_id] = max(mastery.get(node_id, 0.0), 1.0)

    attempts: dict[str, int] = {}
    for attempt in progress.quiz_attempts:
        attempts[attempt.knowledge_point_id] = (
            attempts.get(attempt.knowledge_point_id, 0) + 1
        )

    return LearnerState(mastery=mastery, attempts=attempts)


__all__ = ["learner_state_from_progress"]

"""Teaching policy — deterministic decisions over learner state.

Owns the next-objective gate (``policy``), the mastery scoring policy
(``mastery``), spaced-repetition scheduling (``scheduler``), and the
deterministic Teaching Engine (``engine``).  Answer grading and pending
question state live in ``lumen.modes.learn.assessment``.
"""
from lumen.modes.learn.policy.engine import DEFAULT_POLICY_PRIORITY, TeachingEngine
from lumen.modes.learn.policy.mastery import compute_mastery
from lumen.modes.learn.policy.policy import (
    QUALITATIVE_TYPES,
    QUANTITATIVE_GATE,
    NextStep,
    display_mastery,
    due_reviews,
    find_knowledge_point,
    gate_threshold,
    is_mastered,
    map_summary,
    next_objective,
    objective_status,
)
from lumen.modes.learn.policy.scheduler import INTERVAL_SEQUENCES, SpacedRepetitionScheduler

__all__ = [
    "NextStep", "QUANTITATIVE_GATE", "QUALITATIVE_TYPES",
    "gate_threshold", "is_mastered", "display_mastery",
    "objective_status", "due_reviews", "find_knowledge_point",
    "next_objective", "map_summary",
    "compute_mastery",
    "SpacedRepetitionScheduler", "INTERVAL_SEQUENCES",
    "DEFAULT_POLICY_PRIORITY", "TeachingEngine",
]

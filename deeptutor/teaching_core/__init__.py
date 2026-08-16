"""Teaching Core: explicit teaching model, graph, and deterministic engine."""

from .adapters import learner_state_from_progress
from .engine import TeachingEngine
from .graph import TeachingKnowledgeGraph
from .models import (
    LearnerState,
    LearningGoal,
    TeachingActionType,
    TeachingDecision,
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
)
from .teaching_service import TeachingService

__all__ = [
    "TeachingEngine",
    "TeachingKnowledgeGraph",
    "TeachingKnowledgeModel",
    "TeachingNode",
    "TeachingEdge",
    "TeachingNodeType",
    "TeachingRelationType",
    "TeachingActionType",
    "LearningGoal",
    "LearnerState",
    "TeachingDecision",
    "learner_state_from_progress",
    "TeachingService",
]

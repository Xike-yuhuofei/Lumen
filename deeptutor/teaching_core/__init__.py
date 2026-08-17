"""Deprecated compatibility facade for the Teaching Core.

The canonical teaching stack now lives in ``lumen.modes.learn``
(domain / policy / assessment / application / adapters).  This package
re-exports it for existing importers only; new code must import from
``lumen.modes.learn`` directly.
"""

from lumen.modes.learn.adapters import learner_state_from_progress
from lumen.modes.learn.application.teaching_service import TeachingService
from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
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
from lumen.modes.learn.policy.engine import TeachingEngine

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

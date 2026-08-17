"""Deprecated compatibility facade for the Learner Domain State.

The canonical Learn-mode domain now lives in ``lumen.modes.learn``
(``lumen.modes.learn.domain.models``).  This package re-exports the models for
existing importers only; new code must import from ``lumen.modes.learn``.
"""

from lumen.modes.learn.domain.models import (
    DiagnosticResult,
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    LearningStage,
    QuizAttempt,
    RepetitionState,
    RetryAttempt,
    ReviewTask,
)

__all__ = [
    "DiagnosticResult",
    "ErrorRecord",
    "ErrorType",
    "KnowledgePoint",
    "KnowledgeType",
    "LearningModule",
    "LearningProgress",
    "LearningStage",
    "QuizAttempt",
    "RepetitionState",
    "RetryAttempt",
    "ReviewTask",
]

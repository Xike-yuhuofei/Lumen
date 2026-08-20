from __future__ import annotations

from enum import Enum
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_KNOWLEDGE_TYPE_LEGACY: dict[str, str] = {
    "记忆型": "memory",
    "概念型": "concept",
    "程序型": "procedure",
    "设计型": "design",
}

_ERROR_TYPE_LEGACY: dict[str, str] = {
    "知识结构性": "structural",
    "理解偏差型": "deviation",
    "应用错误": "application",
    "元认知型": "metacognitive",
}


class KnowledgeType(str, Enum):
    MEMORY = "memory"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    DESIGN = "design"

    @classmethod
    def _missing_(cls, value: object) -> KnowledgeType | None:
        mapped = _KNOWLEDGE_TYPE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


class ErrorType(str, Enum):
    KNOWLEDGE_STRUCTURAL = "structural"
    UNDERSTANDING_DEVIATION = "deviation"
    APPLICATION_ERROR = "application"
    METACOGNITIVE = "metacognitive"

    @classmethod
    def _missing_(cls, value: object) -> ErrorType | None:
        mapped = _ERROR_TYPE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


# Stages removed in the Mastery Path simplification are mapped onto the nearest
# surviving stage so progress persisted by the older engine still deserializes.
_STAGE_LEGACY: dict[str, str] = {
    "diagnostic_phase1": "diagnostic",
    "diagnostic_phase2": "diagnostic",
    "metacognitive_intro": "explain",
    "plan": "explain",
    "pretest": "explain",
    "practice_quiz": "practice",
    "module_test": "review",
}


class LearningStage(str, Enum):
    """The Mastery Path loop: diagnose once, then per knowledge point teach and
    check understanding, then practice the module, diagnose errors, and schedule
    spaced review."""

    DIAGNOSTIC = "diagnostic"
    EXPLAIN = "explain"
    FEYNMAN_CHECK = "feynman_check"
    PRACTICE = "practice"
    ERROR_DIAGNOSIS = "error_diagnosis"
    REVIEW = "review"
    COMPLETED = "completed"

    @classmethod
    def _missing_(cls, value: object) -> LearningStage | None:
        mapped = _STAGE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


class Misconception(BaseModel):
    """A known misconception attached to a knowledge point.

    Authored by the tutor at build time from the material (or teaching
    experience); ``statement`` is the wrong belief in the learner's voice and
    ``correction`` is the canonical correction. The teaching graph materialises
    each entry as a MISCONCEPTION node the engine can remediate.
    """

    model_config = ConfigDict(extra="ignore")

    statement: str
    correction: str = ""


class KnowledgePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: KnowledgeType
    module_id: str
    # Source grounding: a short description of what this objective covers and
    # a locator into the learner's material (e.g. "book#ch2.3").
    description: str = ""
    source_ref: str = ""
    misconceptions: list[Misconception] = Field(default_factory=list)


class LearningModule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    order: int
    pass_threshold: float = 0.7
    knowledge_points: list[KnowledgePoint] = Field(default_factory=list)


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_questions: int = 0
    correct_count: int = 0
    module_mastery: dict[str, float] = Field(default_factory=dict)


class QuizAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    knowledge_point_id: str
    module_id: str = ""
    is_correct: bool
    user_answer: Any = None
    error_type: ErrorType | None = None
    self_attribution: str = ""
    mastery_estimate: float = 0.0
    # What the question tested: "recall" (rote / verbatim), "transfer"
    # (apply the idea to a new situation) or "application". Tagged so the
    # evidence trail distinguishes rote recall from transfer success — the
    # mastery evidence principle ("变化题型 / transfer") is only meaningful
    # if the evidence records which kind of question produced it.
    question_kind: str = "recall"
    # When a wrong answer matched a registered misconception, the graph node
    # id of that misconception (else ""). Server-matched, never model-forged.
    misconception_node_id: str = ""
    timestamp: float = Field(default_factory=time.time)


class RetryAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: float
    is_correct: bool
    attempt_number: int


class ErrorRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    question_id: str
    knowledge_point_id: str
    module_id: str
    error_type: ErrorType
    self_attribution: str = ""
    ai_confirmation: str = ""
    # The matched misconception node id (see QuizAttempt.misconception_node_id);
    # while this record is active/retrying the engine remediates it first.
    misconception_node_id: str = ""
    retry_history: list[RetryAttempt] = Field(default_factory=list)
    status: Literal["active", "retrying", "review", "graduated"] = "active"
    created_at: float = Field(default_factory=time.time)


class RepetitionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interval_index: int = 0
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    next_review_at: float


class ReviewTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_point_id: str
    knowledge_type: KnowledgeType
    due_at: float
    priority: int
    state: RepetitionState


class PendingQuestion(BaseModel):
    """A question posed to the learner and awaiting their answer.

    Persisted so grading is deterministic across turns: the expected answer
    lives here server-side and never round-trips through the model. The tutor
    poses a question with ``mastery_quiz`` (storing this), the learner answers
    on a later turn, and ``mastery_grade`` scores the stored answer.
    """

    model_config = ConfigDict(extra="ignore")

    question_id: str
    knowledge_point_id: str
    module_id: str = ""
    prompt: str = ""
    question_type: str = "short"
    # What this question tests (recall / transfer / application) — recorded on
    # the resulting QuizAttempt so mastery evidence distinguishes question kinds.
    question_kind: str = "recall"
    expected_answer: str = ""
    options: list[str] = Field(default_factory=list)
    # Teaching Graph Candidate lineage: the decision_id / action_id that posed
    # this question.  Persisted with the question so grading after a restart can
    # attribute its evidence back to the exact pedagogical decision — the
    # graph, not the LLM, chose to assess.  Empty for the teaching-hook path.
    decision_id: str = ""
    action_id: str = ""
    # The immutable decision payload (the pose decision) so the graph can commit
    # the resulting evidence under the SAME decision_id (idempotent) on grade —
    # from a fresh process, with no guesswork.  Empty for the teaching-hook path.
    decision_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class LearningProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    book_id: str
    diagnostic: DiagnosticResult | None = None
    modules: list[LearningModule] = Field(default_factory=list)
    # Explicit learning goal (set via mastery_goal / dialogue with the tutor).
    # An empty ``goal_kp_ids`` means "every knowledge point" (the default);
    # otherwise only the listed objectives gate completion. ``goal_name`` is
    # the learner-facing intent ("pass the exam", "read chapter 3", …).
    goal_name: str = ""
    goal_kp_ids: list[str] = Field(default_factory=list)
    # A short learner-facing note about what the goal covers (optional; set at
    # goal creation and shown in the learning-space list, never used by the
    # teaching policy).
    description: str = ""
    # The knowledge space (KB) that supplies this goal's learning material,
    # set when the goal is created from a Library / knowledge-space item.
    # Learn turns mount this KB so the tutor can teach from the material
    # without the learner re-attaching the file. Empty → discover at turn time.
    source_kb: str = ""
    current_module_id: str = ""
    current_stage: LearningStage = LearningStage.DIAGNOSTIC
    current_kp_index: int = 0
    mastery_levels: dict[str, float] = Field(default_factory=dict)
    # Qualitative gate for CONCEPT / DESIGN knowledge points: True once the
    # tutor judges the learner's explanation sufficient (``mastery_assess``).
    # The quantitative ``mastery_levels`` gate covers MEMORY / PROCEDURE.
    qualitative_mastery: dict[str, bool] = Field(default_factory=dict)
    knowledge_types: dict[str, KnowledgeType] = Field(default_factory=dict)
    quiz_attempts: list[QuizAttempt] = Field(default_factory=list)
    error_records: list[ErrorRecord] = Field(default_factory=list)
    repetition_states: dict[str, RepetitionState] = Field(default_factory=dict)
    review_queue: list[ReviewTask] = Field(default_factory=list)
    # A single outstanding question; grading reads its expected answer so the
    # model never has to recall it across turns.
    pending_question: PendingQuestion | None = None
    feynman_retries: dict[str, int] = Field(default_factory=dict)
    feynman_explanations: dict[str, str] = Field(default_factory=dict)
    stage_failure_counts: dict[str, int] = Field(default_factory=dict)
    stage_failure_notes: dict[str, str] = Field(default_factory=dict)
    version: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


__all__ = [
    "KnowledgeType",
    "ErrorType",
    "LearningStage",
    "KnowledgePoint",
    "Misconception",
    "LearningModule",
    "DiagnosticResult",
    "QuizAttempt",
    "RetryAttempt",
    "ErrorRecord",
    "RepetitionState",
    "ReviewTask",
    "PendingQuestion",
    "LearningProgress",
]

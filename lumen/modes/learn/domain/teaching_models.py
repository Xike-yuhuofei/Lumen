"""Canonical Teaching Knowledge Model and Teaching Engine contracts.

This module is the single source of truth for *knowledge facts and knowledge
relations* (Teaching Knowledge Model) plus the typed contracts the Teaching
Engine operates on. It deliberately does NOT store learner state, teaching
actions or assessment history — those live in the Learner Model
(:mod:`lumen.modes.learn.domain.models`) and are projected in here only
through the adapters (:mod:`lumen.modes.learn.adapters.learner_state`).

Domain boundaries (see also the implementation report):

* Knowledge truth / relations  -> this module + :mod:`lumen.modes.learn.domain.teaching_graph`
* LearnerState / MasteryEstimate -> Learner Model (projected via adapters)
* EvidenceBundle               -> Evidence
* AssessmentResult             -> Assessment
* TeachingAction               -> Teaching Engine (:mod:`lumen.modes.learn.policy.engine`)
* LearningGoal / LearningPlan  -> Planning
* ReviewSchedule               -> Review Scheduler (:mod:`lumen.modes.learn.policy.scheduler`)

``KnowledgeType`` is reused (not redefined) from
``lumen.modes.learn.domain.models`` so the teaching layer never keeps a
conflicting second copy.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lumen.modes.learn.domain.models import KnowledgeType

__all__ = [
    "KnowledgeType",
    "TeachingNodeType",
    "TeachingRelationType",
    "TeachingActionType",
    "TeachingStrategy",
    "ScaffoldLevel",
    "EvidenceType",
    "SourceReference",
    "TeachingNode",
    "TeachingEdge",
    "TeachingKnowledgeModel",
    "LearningGoal",
    "LearningPlan",
    "LearnerState",
    "MasteryEstimate",
    "EvidenceItem",
    "EvidenceBundle",
    "AssessmentResult",
    "DecisionTrace",
    "TeachingAction",
    "TeachingDecision",
]


class TeachingNodeType(str, Enum):
    """The role a knowledge unit plays in the teaching graph.

    A ``TeachingNode`` is the canonical **KnowledgeUnit**. The granular roles
    below (concept / procedure / example / misconception / …) tell the Teaching
    Engine and the content generator how a unit should be taught, as opposed to
    ``KnowledgeType`` (memory / concept / procedure / design) which is the
    learner-model's classification reused from ``lumen.modes.learn``.
    """

    LEARNING_OBJECTIVE = "learning_objective"
    CONCEPT = "concept"
    PRINCIPLE = "principle"
    PROCEDURE = "procedure"
    CLAIM = "claim"
    ARGUMENT = "argument"
    EXAMPLE = "example"
    ANALOGY = "analogy"
    MISCONCEPTION = "misconception"
    QUESTION = "question"
    EXPLANATION = "explanation"


class TeachingRelationType(str, Enum):
    """Typed teaching edges.

    Edge direction is always ``source --relation--> target``, e.g.
    ``A --prerequisite_of--> B`` means "A must be learned before B".

    Structural relations:
    * ``prerequisite_of`` — A is a prerequisite of B.
    * ``part_of``          — A is a component / part of B.
    * ``depends_on``       — A functionally depends on B.
    * ``prepares_for``     — A prepares the learner for B (softer than prerequisite).
    * ``requires``         — A is required learning for B (A must be learned before B).

    Teaching relations:
    * ``explains``         — A is an explanation of B.
    * ``supports``         — A supports understanding B.
    * ``example_of``       — A is a concrete example of B.
    * ``analogous_to``     — A is analogous to B.
    * ``contrasts_with``   — A contrasts with B.
    * ``commonly_confused_with`` — A is commonly confused with B (misconception link).
    * ``corrects``         — A corrects misconception B.
    * ``remediates``       — A is a remediation path for B (weak/unknown mastery).
    * ``assesses``         — A (a question/assessment) assesses B.
    """

    PREREQUISITE_OF = "prerequisite_of"
    PART_OF = "part_of"
    DEPENDS_ON = "depends_on"
    PREPARES_FOR = "prepares_for"
    REQUIRES = "requires"
    EXPLAINS = "explains"
    SUPPORTS = "supports"
    EXAMPLE_OF = "example_of"
    ANALOGOUS_TO = "analogous_to"
    CONTRASTS_WITH = "contrasts_with"
    COMMONLY_CONFUSED_WITH = "commonly_confused_with"
    CORRECTS = "corrects"
    REMEDIATES = "remediates"
    ASSESSES = "assesses"

    # Relations that constrain learning order (used by path/gating logic).
    ORDERING_RELATIONS: frozenset["TeachingRelationType"] = frozenset(
        {PREREQUISITE_OF, REQUIRES, PART_OF, DEPENDS_ON, PREPARES_FOR}
    )


class TeachingActionType(str, Enum):
    """What the Teaching Engine tells the tutor to do next."""

    REMEDIATE_MISCONCEPTION = "remediate_misconception"
    RESOLVE_PENDING = "resolve_pending"
    REVIEW = "review"
    REVIEW_PREREQUISITE = "review_prerequisite"
    EXPLAIN = "explain"
    SHOW_EXAMPLE = "show_example"
    PRACTICE = "practice"
    ASSESS = "assess"
    COMPLETE = "complete"


class TeachingStrategy(str, Enum):
    """The concrete teaching strategy attached to a TeachingAction."""

    EXPLAIN_DIRECT = "explain_direct"
    WORKED_EXAMPLE = "worked_example"
    ANALOGY = "analogy"
    SOCRATIC = "socratic"
    SCAFFOLDED_PRACTICE = "scaffolded_practice"
    FEYNMAN_CHECK = "feynman_check"
    SPACED_REVIEW = "spaced_review"
    MISCONCEPTION_CORRECTION = "misconception_correction"
    NONE = "none"


class ScaffoldLevel(str, Enum):
    """How much support the next step should carry (escalate then fade)."""

    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    FULL = "full"


class EvidenceType(str, Enum):
    """Kinds of evidence the engine expects a TeachingAction to elicit."""

    QUIZ_ANSWER = "quiz_answer"
    FEYNMAN_EXPLANATION = "feynman_explanation"
    REVIEW_ANSWER = "review_answer"
    SELF_REPORT = "self_report"


class SourceReference(BaseModel):
    """A typed pointer into a learning source (book / document / excerpt).

    ``ref()`` renders the canonical locator string stored on
    :attr:`TeachingNode.source_refs`.
    """

    model_config = ConfigDict(extra="ignore")

    source_id: str
    locator: str = ""
    heading: str = ""
    excerpt: str = ""

    @field_validator("source_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_id must not be blank")
        return value

    def ref(self) -> str:
        if self.locator:
            return f"{self.source_id}#{self.locator}"
        return self.source_id


class TeachingNode(BaseModel):
    """A KnowledgeUnit in the canonical Teaching Knowledge Model."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    type: TeachingNodeType
    content: str = ""
    # Canonical locator strings (``<source_id>#<locator>``). Richer provenance
    # can travel in ``metadata`` (e.g. ``source_anchors`` from extraction).
    source_refs: list[str] = Field(default_factory=list)
    # Teaching metadata.
    difficulty: float = 0.5
    importance: float = 0.5
    teachability: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("difficulty", "importance", "teachability")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("teaching metadata must be between 0 and 1")
        return value


class TeachingEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    relation: TeachingRelationType
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("weight")
    @classmethod
    def _valid_weight(cls, value: float) -> float:
        if value < 0:
            raise ValueError("weight must be >= 0")
        return value


class TeachingKnowledgeModel(BaseModel):
    """The canonical Teaching Knowledge Model: nodes + teaching edges."""

    model_config = ConfigDict(extra="ignore")

    nodes: list[TeachingNode] = Field(default_factory=list)
    edges: list[TeachingEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "TeachingKnowledgeModel":
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("teaching node ids must be unique")
        known = set(ids)
        dangling = [
            f"{edge.source}->{edge.target}"
            for edge in self.edges
            if edge.source not in known or edge.target not in known
        ]
        if dangling:
            raise ValueError(f"edges reference unknown nodes: {', '.join(dangling)}")
        return self


# ── Planning (LearningGoal / LearningPlan) ───────────────────────────────


class LearningGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    description: str = ""
    target_node_ids: list[str]
    mastery_threshold: float = 0.8
    prerequisite_threshold: float = 0.7
    # Per-node mastery gates keyed by node id. When a node has an entry it
    # overrides ``mastery_threshold`` for that node — this is how the engine
    # and the per-type mastery gates (``policy.gate_threshold``) stay a single
    # decision authority: quantitative types gate at 0.9, qualitative types
    # gate at 1.0 (a qualitative pass projects to full mastery).
    node_thresholds: dict[str, float] = Field(default_factory=dict)

    @field_validator("mastery_threshold", "prerequisite_threshold")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        return value

    @field_validator("node_thresholds")
    @classmethod
    def _valid_node_thresholds(cls, value: dict[str, float]) -> dict[str, float]:
        for node_id, threshold in value.items():
            if not 0.0 <= threshold <= 1.0:
                raise ValueError(f"node_thresholds[{node_id!r}] must be between 0 and 1")
        return value

    def threshold_for(self, node_id: str) -> float:
        """The mastery gate that applies to *node_id* (per-node override, else
        the goal-wide threshold)."""
        return self.node_thresholds.get(node_id, self.mastery_threshold)


class LearningPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str = ""
    goals: list[LearningGoal] = Field(default_factory=list)
    review_default_interval: int = 1

    @field_validator("id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("plan id must not be blank")
        return value


# ── Learner Model projection (used by the engine, owned by lumen.modes.learn) ──


class LearnerState(BaseModel):
    """A deterministic projection of the Learner Model for the Teaching Engine.

    The engine never writes this; adapters project it from
    ``lumen.modes.learn.LearningProgress``.
    """

    model_config = ConfigDict(extra="ignore")

    mastery: dict[str, float] = Field(default_factory=dict)
    attempts: dict[str, int] = Field(default_factory=dict)
    misconceptions: set[str] = Field(default_factory=set)
    # Node ids that are due for spaced-repetition review. Resolved by the
    # adapter at a fixed ``now`` so the engine itself stays time-free and
    # deterministically replayable.
    due_reviews: list[str] = Field(default_factory=list)
    # A posed question is awaiting the learner's answer (must be graded first).
    pending_answer: bool = False
    # The node whose question is awaiting an answer (only when pending_answer).
    pending_node_id: str = ""

    @field_validator("mastery")
    @classmethod
    def _valid_mastery(cls, value: dict[str, float]) -> dict[str, float]:
        for node_id, score in value.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"mastery[{node_id!r}] must be between 0 and 1")
        return value

    @field_validator("attempts")
    @classmethod
    def _valid_attempts(cls, value: dict[str, int]) -> dict[str, int]:
        for node_id, count in value.items():
            if count < 0:
                raise ValueError(f"attempts[{node_id!r}] must be >= 0")
        return value


class MasteryEstimate(BaseModel):
    """Per-unit mastery with the evidence it was derived from."""

    model_config = ConfigDict(extra="ignore")

    node_id: str
    score: float = 0.0
    confidence: float = 0.0
    evidence_count: int = 0
    threshold: float = 0.8
    mastered: bool = False

    @field_validator("score", "confidence", "threshold")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0 and 1")
        return value


# ── Evidence / Assessment ────────────────────────────────────────────────


class EvidenceItem(BaseModel):
    """One unit of evidence about a knowledge unit."""

    model_config = ConfigDict(extra="ignore")

    node_id: str
    kind: EvidenceType
    outcome: bool
    detail: str = ""
    at: float = Field(default_factory=time.time)


class EvidenceBundle(BaseModel):
    """A collected set of evidence — the input to mastery estimation."""

    model_config = ConfigDict(extra="ignore")

    items: list[EvidenceItem] = Field(default_factory=list)

    def for_node(self, node_id: str) -> list[EvidenceItem]:
        return [item for item in self.items if item.node_id == node_id]

    def count(self, node_id: str, *, kind: EvidenceType | None = None) -> int:
        return len(
            [
                item
                for item in self.items
                if item.node_id == node_id and (kind is None or item.kind == kind)
            ]
        )


class AssessmentResult(BaseModel):
    """The result of one assessment — owned by the Assessment boundary.

    Note: an ``AssessmentResult`` is NOT a ``MasteryEstimate``; mastery is
    estimated from accumulated evidence, assessment results are one input.
    """

    model_config = ConfigDict(extra="ignore")

    node_id: str
    question_id: str = ""
    kind: EvidenceType = EvidenceType.QUIZ_ANSWER
    is_correct: bool
    error_type: str = ""
    mastery_after: float = 0.0
    threshold: float = 0.0

    def to_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            node_id=self.node_id,
            kind=self.kind,
            outcome=self.is_correct,
            detail=f"q:{self.question_id} error:{self.error_type}",
        )


# ── Decision Trace ───────────────────────────────────────────────────────


class DecisionTrace(BaseModel):
    """A structured, deterministic record of how a TeachingAction was chosen."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    policy_applied: str = ""
    policies_evaluated: list[str] = Field(default_factory=list)
    gates: dict[str, Any] = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)


# ── TeachingAction (engine output) ───────────────────────────────────────


class TeachingAction(BaseModel):
    """The unified output of the Teaching Engine.

    The engine owns *what happens next*; the LLM / capability only turns this
    into concrete content. The model has no authority to change the action.
    """

    model_config = ConfigDict(extra="ignore")

    action: TeachingActionType
    focus_node_id: str = ""
    strategy: TeachingStrategy = TeachingStrategy.NONE
    scaffold_level: ScaffoldLevel = ScaffoldLevel.NONE
    expected_evidence: EvidenceType = EvidenceType.QUIZ_ANSWER
    success_condition: str = ""
    reason: str = ""
    resource_node_ids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    trace: DecisionTrace = Field(default_factory=DecisionTrace)

    @property
    def target_node_id(self) -> str:
        """Alias: the target knowledge unit of this action."""
        return self.focus_node_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "target_node_id": self.focus_node_id,
            "strategy": self.strategy.value,
            "scaffold_level": self.scaffold_level.value,
            "expected_evidence": self.expected_evidence.value,
            "success_condition": self.success_condition,
            "reason": self.reason,
            "resource_node_ids": list(self.resource_node_ids),
            "constraints": list(self.constraints),
            "trace": self.trace.model_dump(),
        }


# Backwards-compatible name for the engine's decision output.
TeachingDecision = TeachingAction

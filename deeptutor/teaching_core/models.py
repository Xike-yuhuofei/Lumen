from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TeachingNodeType(str, Enum):
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
    PREREQUISITE_OF = "prerequisite_of"
    EXPLAINS = "explains"
    EXAMPLE_OF = "example_of"
    ANALOGOUS_TO = "analogous_to"
    CORRECTS = "corrects"
    ASSESSES = "assesses"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REQUIRES = "requires"


class TeachingActionType(str, Enum):
    REMEDIATE_MISCONCEPTION = "remediate_misconception"
    REVIEW_PREREQUISITE = "review_prerequisite"
    EXPLAIN = "explain"
    SHOW_EXAMPLE = "show_example"
    ASSESS = "assess"
    COMPLETE = "complete"


class TeachingNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    type: TeachingNodeType
    content: str = ""
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
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


class LearningGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_node_ids: list[str]
    mastery_threshold: float = 0.8
    prerequisite_threshold: float = 0.7

    @field_validator("mastery_threshold", "prerequisite_threshold")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        return value


class LearnerState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mastery: dict[str, float] = Field(default_factory=dict)
    attempts: dict[str, int] = Field(default_factory=dict)
    misconceptions: set[str] = Field(default_factory=set)

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


class TeachingDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: TeachingActionType
    focus_node_id: str = ""
    resource_node_ids: list[str] = Field(default_factory=list)
    reason: str
    trace: list[str] = Field(default_factory=list)


__all__ = [
    "TeachingNodeType",
    "TeachingRelationType",
    "TeachingActionType",
    "TeachingNode",
    "TeachingEdge",
    "TeachingKnowledgeModel",
    "LearningGoal",
    "LearnerState",
    "TeachingDecision",
]

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deeptutor.teaching_core.models import (
    TeachingKnowledgeModel,
    TeachingNodeType,
    TeachingRelationType,
)


class SourceAnchor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_hash: str = ""
    segment_id: str
    locator: str
    block_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    heading: str = ""

    def ref(self) -> str:
        return f"{self.source_id}#{self.locator}"


class SourceSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    anchor: SourceAnchor
    text: str


class ExtractedNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    type: TeachingNodeType
    content: str = ""
    source_segment_ids: list[str] = Field(default_factory=list)
    evidence_quote: str = ""
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class ExtractedEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    relation: TeachingRelationType
    source_segment_ids: list[str] = Field(default_factory=list)
    evidence_quote: str = ""
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    model: TeachingKnowledgeModel
    segment_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "SourceAnchor",
    "SourceSegment",
    "ExtractedNode",
    "ExtractedEdge",
    "ExtractionBatch",
    "ExtractionResult",
]

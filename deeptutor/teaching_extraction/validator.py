from __future__ import annotations

import re

from deeptutor.teaching_core.graph import TeachingKnowledgeGraph
from deeptutor.teaching_core.models import TeachingKnowledgeModel

from .schemas import ExtractionBatch


class TeachingExtractionValidationError(ValueError):
    pass


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _validate_evidence(
    *,
    label: str,
    evidence_quote: str,
    source_segment_ids: list[str],
    source_segments: dict[str, str] | None,
) -> None:
    if not evidence_quote.strip():
        raise TeachingExtractionValidationError(f"{label} has no evidence_quote")
    if source_segments is None:
        return

    needle = _normalize_ws(evidence_quote)
    if not needle:
        raise TeachingExtractionValidationError(f"{label} has blank evidence_quote")
    if not any(
        needle in _normalize_ws(source_segments.get(segment_id, ""))
        for segment_id in source_segment_ids
    ):
        raise TeachingExtractionValidationError(
            f"{label} evidence_quote is not present in its cited source segment"
        )


def validate_batch(
    batch: ExtractionBatch,
    *,
    allowed_segment_ids: set[str],
    source_segments: dict[str, str] | None = None,
) -> None:
    node_ids = [node.id for node in batch.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise TeachingExtractionValidationError("extracted node ids must be unique within a batch")

    known_nodes = set(node_ids)
    for node in batch.nodes:
        if not node.source_segment_ids:
            raise TeachingExtractionValidationError(f"node {node.id!r} has no source_segment_ids")
        unknown = set(node.source_segment_ids) - allowed_segment_ids
        if unknown:
            raise TeachingExtractionValidationError(
                f"node {node.id!r} references unknown source segments: {sorted(unknown)}"
            )
        _validate_evidence(
            label=f"node {node.id!r}",
            evidence_quote=node.evidence_quote,
            source_segment_ids=node.source_segment_ids,
            source_segments=source_segments,
        )

    for edge in batch.edges:
        if edge.source not in known_nodes or edge.target not in known_nodes:
            raise TeachingExtractionValidationError(
                f"edge {edge.source!r}->{edge.target!r} references an unknown local node"
            )
        if not edge.source_segment_ids:
            raise TeachingExtractionValidationError(
                f"edge {edge.source!r}->{edge.target!r} has no source_segment_ids"
            )
        unknown = set(edge.source_segment_ids) - allowed_segment_ids
        if unknown:
            raise TeachingExtractionValidationError(
                f"edge references unknown source segments: {sorted(unknown)}"
            )
        _validate_evidence(
            label=f"edge {edge.source!r}->{edge.target!r}",
            evidence_quote=edge.evidence_quote,
            source_segment_ids=edge.source_segment_ids,
            source_segments=source_segments,
        )


def validate_model(model: TeachingKnowledgeModel) -> None:
    graph = TeachingKnowledgeGraph(model)
    try:
        graph.topological_order()
    except ValueError as exc:
        raise TeachingExtractionValidationError(str(exc)) from exc


__all__ = [
    "TeachingExtractionValidationError",
    "validate_batch",
    "validate_model",
]

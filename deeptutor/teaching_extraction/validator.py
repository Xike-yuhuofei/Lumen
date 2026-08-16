from __future__ import annotations

from deeptutor.teaching_core.graph import TeachingKnowledgeGraph
from deeptutor.teaching_core.models import TeachingKnowledgeModel

from .schemas import ExtractionBatch


class TeachingExtractionValidationError(ValueError):
    pass


def validate_batch(batch: ExtractionBatch, *, allowed_segment_ids: set[str]) -> None:
    node_ids = [node.id for node in batch.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise TeachingExtractionValidationError(
            "extracted node ids must be unique within a batch"
        )

    known_nodes = set(node_ids)
    for node in batch.nodes:
        if not node.source_segment_ids:
            raise TeachingExtractionValidationError(
                f"node {node.id!r} has no source_segment_ids"
            )
        unknown = set(node.source_segment_ids) - allowed_segment_ids
        if unknown:
            raise TeachingExtractionValidationError(
                f"node {node.id!r} references unknown source segments: {sorted(unknown)}"
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

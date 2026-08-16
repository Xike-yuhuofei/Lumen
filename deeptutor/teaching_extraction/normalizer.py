from __future__ import annotations

from collections import defaultdict
import hashlib
import re
from typing import Iterable
import unicodedata

from deeptutor.teaching_core.models import (
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
)

from .schemas import ExtractionBatch, SourceAnchor
from .validator import validate_model


def _norm_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", value)


def _canonical_node_id(source_id: str, node_type: str, title: str) -> str:
    key = f"{source_id}|{node_type}|{_norm_title(title)}".encode("utf-8")
    return f"tk_{node_type}_{hashlib.sha1(key).hexdigest()[:12]}"


def _anchor_dict(anchor: SourceAnchor) -> dict:
    return anchor.model_dump(exclude_none=True)


def normalize_batches(
    batches: Iterable[ExtractionBatch],
    *,
    source_id: str,
    anchors: dict[str, SourceAnchor],
) -> TeachingKnowledgeModel:
    batch_list = list(batches)
    canonical: dict[tuple[str, str], TeachingNode] = {}
    local_to_canonical: dict[tuple[int, str], str] = {}
    node_anchor_ids: dict[str, set[str]] = defaultdict(set)
    node_confidence: dict[str, float] = {}
    node_evidence: dict[str, set[str]] = defaultdict(set)

    for batch_index, batch in enumerate(batch_list):
        for raw in batch.nodes:
            key = (raw.type.value, _norm_title(raw.title))
            node = canonical.get(key)
            if node is None:
                node_id = _canonical_node_id(source_id, raw.type.value, raw.title)
                node = TeachingNode(
                    id=node_id,
                    title=raw.title.strip(),
                    type=raw.type,
                    content=raw.content.strip(),
                    metadata={"extracted": True},
                )
                canonical[key] = node
            elif len(raw.content.strip()) > len(node.content):
                node.content = raw.content.strip()

            local_to_canonical[(batch_index, raw.id)] = node.id
            node_anchor_ids[node.id].update(raw.source_segment_ids)
            if raw.evidence_quote.strip():
                node_evidence[node.id].add(raw.evidence_quote.strip())
            node_confidence[node.id] = max(node_confidence.get(node.id, 0.0), raw.confidence)

    nodes = list(canonical.values())
    for node in nodes:
        segment_ids = sorted(node_anchor_ids[node.id])
        node.source_refs = [anchors[sid].ref() for sid in segment_ids]
        node.metadata = {
            **node.metadata,
            "confidence": round(node_confidence.get(node.id, 0.0), 4),
            "source_anchors": [_anchor_dict(anchors[sid]) for sid in segment_ids],
            "evidence_quotes": sorted(node_evidence[node.id]),
        }

    edge_map: dict[tuple[str, str, str], TeachingEdge] = {}
    edge_anchor_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    edge_evidence: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for batch_index, batch in enumerate(batch_list):
        for raw in batch.edges:
            source = local_to_canonical[(batch_index, raw.source)]
            target = local_to_canonical[(batch_index, raw.target)]
            if source == target:
                continue
            key = (source, target, raw.relation.value)
            edge = edge_map.get(key)
            if edge is None:
                edge = TeachingEdge(
                    source=source,
                    target=target,
                    relation=raw.relation,
                    weight=raw.confidence,
                    metadata={"extracted": True, "confidence": raw.confidence},
                )
                edge_map[key] = edge
            else:
                edge.weight = max(edge.weight, raw.confidence)
                edge.metadata["confidence"] = max(
                    float(edge.metadata.get("confidence", 0.0)), raw.confidence
                )
            edge_anchor_ids[key].update(raw.source_segment_ids)
            if raw.evidence_quote.strip():
                edge_evidence[key].add(raw.evidence_quote.strip())

    edges = list(edge_map.values())
    for key, edge in edge_map.items():
        segment_ids = sorted(edge_anchor_ids[key])
        edge.metadata["source_refs"] = [anchors[sid].ref() for sid in segment_ids]
        edge.metadata["source_anchors"] = [_anchor_dict(anchors[sid]) for sid in segment_ids]
        edge.metadata["evidence_quotes"] = sorted(edge_evidence[key])

    model = TeachingKnowledgeModel(
        nodes=sorted(nodes, key=lambda node: node.id),
        edges=sorted(
            edges,
            key=lambda edge: (edge.source, edge.target, edge.relation.value),
        ),
    )
    validate_model(model)
    return model


__all__ = ["normalize_batches"]

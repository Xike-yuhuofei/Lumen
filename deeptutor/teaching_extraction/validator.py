from __future__ import annotations

import difflib
import re

from deeptutor.teaching_core.graph import TeachingKnowledgeGraph
from deeptutor.teaching_core.models import TeachingKnowledgeModel

from .schemas import ExtractionBatch


class TeachingExtractionValidationError(ValueError):
    pass


def _strip_markdown(value: str) -> str:
    """Remove Markdown structural markers that would otherwise break verbatim
    quote matching (blockquotes, list bullets/numbers, headings, emphasis,
    inline code).

    These are presentation syntax, not content, so a quote copied from a
    ``> blockquote``, ``- list`` or ``**bold**`` line must still match the
    underlying text. Content characters are left untouched.
    """
    value = re.sub(r"(?m)^[ \t]*>[ \t]?", "", value)  # blockquote
    value = re.sub(r"(?m)^[ \t]*[-*+][ \t]+", "", value)  # unordered list
    value = re.sub(r"(?m)^[ \t]*\d+[.)][ \t]+", "", value)  # ordered list
    value = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+", "", value)  # ATX headings
    value = value.replace("**", "").replace("__", "").replace("`", "")
    # Single emphasis delimiters: a star only when it is not part of a word.
    value = re.sub(r"(?<!\w)\*(?!\w)", "", value)
    return value


def _compact(value: str) -> str:
    """Whitespace-insensitive form for CJK-safe substring matching.

    Chinese text carries no inter-word spaces, so ``转化：\n\n> 原来`` and
    ``转化：原来`` are the same quote once Markdown markers are stripped.
    Removing all whitespace makes the grounding check robust to line breaks
    while still rejecting fully-invented quotes.
    """
    return re.sub(r"\s+", "", value)


# Trailing punctuation an LLM may append to a verbatim excerpt without changing
# its content. Stripping it before the grounding check keeps evidence honest
# while tolerating cosmetic terminal punctuation.
_TERMINAL_PUNCT = "。.!！?？；;，,、…：:·-–—~～'\"\u2018\u2019\u201c\u201d"


def _ground_evidence(evidence_quote: str, segment_text: str) -> str | None:
    """Return the verbatim source quote for a candidate, or ``None``.

    All comparisons run on markdown-stripped, whitespace-insensitive forms.

    1. Exact match keeps the candidate.
    2. Candidate minus terminal punctuation still matches -> keep candidate.
    3. Otherwise snap the candidate to the closest contiguous verbatim span in
       the source via ``difflib``; accept only when the matched span covers a
       clear majority of the candidate. This tolerates LLM drift (dropped
       particles, re-ordered conjunctions) while still rejecting invented text.
    """
    needle = _compact(_strip_markdown(evidence_quote))
    hay = _compact(_strip_markdown(segment_text))
    if not needle or not hay:
        return None
    if needle in hay:
        return evidence_quote.strip()

    base = needle.rstrip(_TERMINAL_PUNCT)
    if len(base) >= 6 and base in hay:
        return base

    matcher = difflib.SequenceMatcher(None, needle, hay, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
    if not blocks:
        return None
    matched = sum(block.size for block in blocks)
    first_a = min(block.a for block in blocks)
    last_a = max(block.a + block.size for block in blocks)
    if matched / len(needle) < 0.6 or (last_a - first_a) / len(needle) < 0.6:
        return None
    span_start = min(block.b for block in blocks)
    span_end = max(block.b + block.size for block in blocks)
    span = hay[span_start:span_end]
    return span or None


def _validate_evidence(
    *,
    label: str,
    evidence_quote: str,
    source_segment_ids: list[str],
    source_segments: dict[str, str] | None,
) -> str | None:
    """Validate that a quote is grounded in its cited segment.

    Returns the corrected verbatim quote (snapped to source text) when the
    candidate is acceptable, or ``None`` when the quote is blank.
    Raises :class:`TeachingExtractionValidationError` when the quote is not
    grounded in any cited segment.
    """
    if not evidence_quote.strip():
        raise TeachingExtractionValidationError(f"{label} has no evidence_quote")
    if source_segments is None:
        return evidence_quote.strip()

    for segment_id in source_segment_ids:
        grounded = _ground_evidence(evidence_quote, source_segments.get(segment_id, ""))
        if grounded:
            return grounded
    raise TeachingExtractionValidationError(
        f"{label} evidence_quote is not grounded in its cited source segment"
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
        corrected = _validate_evidence(
            label=f"node {node.id!r}",
            evidence_quote=node.evidence_quote,
            source_segment_ids=node.source_segment_ids,
            source_segments=source_segments,
        )
        if corrected is not None:
            node.evidence_quote = corrected

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
        corrected = _validate_evidence(
            label=f"edge {edge.source!r}->{edge.target!r}",
            evidence_quote=edge.evidence_quote,
            source_segment_ids=edge.source_segment_ids,
            source_segments=source_segments,
        )
        if corrected is not None:
            edge.evidence_quote = corrected


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

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.teaching_core.models import TeachingNodeType, TeachingRelationType

from .normalizer import normalize_batches
from .schemas import ExtractionBatch, ExtractionResult, SourceSegment
from .source_anchor import segment_parsed_document
from .validator import TeachingExtractionValidationError, validate_batch

CompleteFn = Callable[..., Awaitable[str]]


class TeachingExtractionError(RuntimeError):
    pass


_SYSTEM_PROMPT = """You extract a pedagogical knowledge model from source material.
Return JSON only. Never invent facts or relationships not supported by the supplied source.
Create atomic, reusable teaching nodes and pedagogically meaningful relations.
Every node and edge must cite the supplied segment_id in source_segment_ids.
Prefer a small number of high-value nodes over exhaustive sentence extraction.
Use misconceptions only when the source explicitly addresses a likely or stated misunderstanding.
"""


def _schema_instructions(segment_id: str) -> str:
    node_types = ", ".join(item.value for item in TeachingNodeType)
    relation_types = ", ".join(item.value for item in TeachingRelationType)
    return f"""Allowed node types: {node_types}
Allowed relation types: {relation_types}

Output exactly:
{{
  "nodes": [
    {{
      "id": "n1",
      "title": "...",
      "type": "concept",
      "content": "...",
      "source_segment_ids": ["{segment_id}"],
      "confidence": 0.0
    }}
  ],
  "edges": [
    {{
      "source": "n1",
      "target": "n2",
      "relation": "prerequisite_of",
      "source_segment_ids": ["{segment_id}"],
      "confidence": 0.0
    }}
  ]
}}

Relation direction is semantic:
A prerequisite_of B means A must be understood before B.
A explains B means A is an explanatory resource for B.
A example_of B means A is an example of B.
A corrects B means A corrects misconception B.
"""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else stripped


def _parse_batch(text: str) -> ExtractionBatch:
    payload_text = _strip_code_fence(text)
    try:
        payload: Any = json.loads(payload_text)
    except json.JSONDecodeError:
        try:
            from json_repair import loads as repair_loads
        except ImportError as exc:
            raise TeachingExtractionError("LLM returned invalid JSON") from exc
        try:
            payload = repair_loads(payload_text)
        except Exception as exc:
            raise TeachingExtractionError("LLM returned invalid JSON") from exc
    try:
        return ExtractionBatch.model_validate(payload)
    except Exception as exc:
        raise TeachingExtractionError(
            f"LLM output does not match extraction schema: {exc}"
        ) from exc


async def _default_complete(*, prompt: str, system_prompt: str) -> str:
    from deeptutor.services.llm import complete

    return await complete(prompt=prompt, system_prompt=system_prompt)


class TeachingKnowledgeExtractor:
    def __init__(
        self,
        *,
        complete_fn: CompleteFn | None = None,
        max_segment_chars: int = 12000,
    ) -> None:
        self._complete = complete_fn or _default_complete
        self._max_segment_chars = max_segment_chars

    async def _extract_segment(self, segment: SourceSegment) -> ExtractionBatch:
        prompt = (
            _schema_instructions(segment.anchor.segment_id)
            + "\n\nSOURCE SEGMENT\n"
            + f"segment_id: {segment.anchor.segment_id}\n"
            + f"locator: {segment.anchor.locator}\n"
            + f"heading: {segment.anchor.heading or '(none)'}\n\n"
            + segment.text
        )
        try:
            raw = await self._complete(prompt=prompt, system_prompt=_SYSTEM_PROMPT)
            batch = _parse_batch(raw)
            validate_batch(
                batch,
                allowed_segment_ids={segment.anchor.segment_id},
            )
            return batch
        except TeachingExtractionValidationError as exc:
            raise TeachingExtractionError(
                f"invalid extraction for {segment.anchor.segment_id}: {exc}"
            ) from exc

    async def extract(
        self,
        document: ParsedDocument,
        *,
        source_id: str,
    ) -> ExtractionResult:
        source_id = source_id.strip()
        if not source_id:
            raise ValueError("source_id must not be blank")

        segments = segment_parsed_document(
            document,
            source_id=source_id,
            max_chars=self._max_segment_chars,
        )
        if not segments:
            raise TeachingExtractionError("parsed document contains no extractable text")

        batches: list[ExtractionBatch] = []
        for segment in segments:
            batches.append(await self._extract_segment(segment))

        anchors = {segment.anchor.segment_id: segment.anchor for segment in segments}
        model = normalize_batches(batches, source_id=source_id, anchors=anchors)
        return ExtractionResult(
            source_id=source_id,
            model=model,
            segment_count=len(segments),
            node_count=len(model.nodes),
            edge_count=len(model.edges),
        )


__all__ = [
    "TeachingExtractionError",
    "TeachingKnowledgeExtractor",
]

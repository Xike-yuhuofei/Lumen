from __future__ import annotations

import hashlib
import re
from typing import Any

from deeptutor.services.parsing.types import ParsedDocument

from .schemas import SourceAnchor, SourceSegment

_TEXT_KEYS = ("text", "content", "markdown", "value", "caption")
_CHILD_KEYS = ("children", "items", "lines", "spans")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")


def _stable_segment_id(source_id: str, source_hash: str, locator: str) -> str:
    raw = f"{source_id}|{source_hash}|{locator}".encode("utf-8")
    return "seg_" + hashlib.sha1(raw).hexdigest()[:16]


def _block_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _block_text(item))).strip()
    if not isinstance(value, dict):
        return ""
    for key in _TEXT_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    parts: list[str] = []
    for key in _CHILD_KEYS:
        child = value.get(key)
        if child is not None:
            text = _block_text(child)
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _heading_for_markdown(markdown: str, start: int) -> str:
    # If this segment begins at a heading, that heading owns the segment.
    at_start = _HEADING_RE.match(markdown, start)
    if at_start:
        return at_start.group(1).strip()
    prefix = markdown[:start]
    matches = list(_HEADING_RE.finditer(prefix))
    return matches[-1].group(1).strip() if matches else ""


def _preferred_heading_boundary(
    markdown: str,
    *,
    start: int,
    hard_end: int,
    max_chars: int,
) -> int | None:
    """Prefer a semantic section boundary before a generic character cut.

    A heading is used only after roughly one third of the window so tiny
    subsections are not emitted as separate LLM calls. This keeps chapter-scale
    material coherent while preventing one segment from crossing into the next
    chapter/major section when Markdown headings are available.
    """
    lower_bound = start + max(max_chars // 3, 1)
    if lower_bound >= hard_end:
        return None
    match = _HEADING_RE.search(markdown, lower_bound, hard_end)
    if match and match.start() > start:
        return match.start()
    return None


def _markdown_segments(
    markdown: str,
    *,
    source_id: str,
    source_hash: str,
    max_chars: int,
) -> list[SourceSegment]:
    segments: list[SourceSegment] = []
    start = 0
    length = len(markdown)
    while start < length:
        while start < length and markdown[start].isspace():
            start += 1
        if start >= length:
            break
        hard_end = min(start + max_chars, length)
        end = hard_end
        if hard_end < length:
            heading_boundary = _preferred_heading_boundary(
                markdown,
                start=start,
                hard_end=hard_end,
                max_chars=max_chars,
            )
            if heading_boundary is not None:
                end = heading_boundary
            else:
                lower_bound = start + max(max_chars // 2, 1)
                boundary = markdown.rfind("\n\n", lower_bound, hard_end)
                if boundary > start:
                    end = boundary
        while end > start and markdown[end - 1].isspace():
            end -= 1
        if end <= start:
            end = hard_end
        text = markdown[start:end].strip()
        locator = f"chars:{start}-{end}"
        anchor = SourceAnchor(
            source_id=source_id,
            source_hash=source_hash,
            segment_id=_stable_segment_id(source_id, source_hash, locator),
            locator=locator,
            start_char=start,
            end_char=end,
            heading=_heading_for_markdown(markdown, start),
        )
        segments.append(SourceSegment(anchor=anchor, text=text))
        start = max(end, start + 1)
    return segments


def segment_parsed_document(
    document: ParsedDocument,
    *,
    source_id: str,
    max_chars: int = 12000,
) -> list[SourceSegment]:
    if max_chars < 1000:
        raise ValueError("max_chars must be >= 1000")

    if document.blocks:
        segments: list[SourceSegment] = []
        for index, block in enumerate(document.blocks):
            text = _block_text(block)
            if not text:
                continue
            if len(text) > max_chars:
                nested = _markdown_segments(
                    text,
                    source_id=source_id,
                    source_hash=document.source_hash,
                    max_chars=max_chars,
                )
                for part_no, segment in enumerate(nested):
                    locator = f"block:{index}/part:{part_no}"
                    segment.anchor.locator = locator
                    segment.anchor.block_index = index
                    segment.anchor.segment_id = _stable_segment_id(
                        source_id, document.source_hash, locator
                    )
                segments.extend(nested)
                continue

            locator = f"block:{index}"
            anchor = SourceAnchor(
                source_id=source_id,
                source_hash=document.source_hash,
                segment_id=_stable_segment_id(source_id, document.source_hash, locator),
                locator=locator,
                block_index=index,
            )
            segments.append(SourceSegment(anchor=anchor, text=text))
        if segments:
            return segments

    return _markdown_segments(
        document.markdown or "",
        source_id=source_id,
        source_hash=document.source_hash,
        max_chars=max_chars,
    )


__all__ = ["segment_parsed_document"]

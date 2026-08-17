"""Pure text-cleaning helpers for model output and speech rendering.

Owned by ``lumen`` (single real implementation). ``deeptutor`` re-exports
these from here for existing importers only.
"""

from __future__ import annotations

import re


def clean_thinking_tags(
    content: str,
    binding: str | None = None,  # noqa: ARG001 (kept for signature compat)
    model: str | None = None,  # noqa: ARG001
) -> str:
    """Remove  thinking tags from model output."""
    if not content:
        return ""

    closed_pattern = re.compile(
        r"`?<\s*(?P<tag>think(?:ing)?)\b[^>]*>`?.*?`?<\s*/\s*(?P=tag)\s*>`?",
        re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(closed_pattern, "", content)
    # Streaming providers can surface a final partial block if the request is
    # interrupted after reasoning has started. Never expose that scratchpad.
    unclosed_pattern = re.compile(
        r"`?<\s*think(?:ing)?\b[^>]*>`?.*$",
        re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(unclosed_pattern, "", cleaned)
    cleaned = re.sub(r"`?<\s*/\s*think(?:ing)?\s*>`?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# Content blocks that should never be spoken aloud, stripped before synthesis.
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(\S.*?\S|\S)\1")
_HTML_TAG = re.compile(r"<[^>]+>")
_TABLE_PIPE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def strip_markdown_for_speech(text: str, *, max_chars: int = 0) -> str:
    """Reduce Markdown to plain prose suitable for TTS.

    Drops code blocks and tables outright (they read terribly), unwraps links
    and emphasis to their visible text, and removes structural markers. This is
    deliberately lossy — the goal is natural speech, not faithful rendering.
    """
    if not text:
        return ""
    out = _FENCED_CODE.sub(" ", text)
    out = _TABLE_PIPE.sub(" ", out)
    out = _IMAGE.sub(" ", out)
    out = _LINK.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _BLOCKQUOTE.sub("", out)
    out = _LIST_MARKER.sub("", out)
    out = _EMPHASIS.sub(r"\2", out)
    out = _HTML_TAG.sub("", out)
    out = _WHITESPACE.sub(" ", out)
    out = _BLANK_LINES.sub("\n\n", out).strip()
    if max_chars and len(out) > max_chars:
        # Cut on a sentence/space boundary near the cap so speech ends cleanly.
        window = out[:max_chars]
        cut = max(window.rfind("."), window.rfind("\n"), window.rfind(" "))
        out = window[: cut + 1].strip() if cut > max_chars // 2 else window.strip()
    return out


__all__ = ["clean_thinking_tags", "strip_markdown_for_speech"]

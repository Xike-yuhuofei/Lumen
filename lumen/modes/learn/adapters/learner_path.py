"""Learner-path identifier resolution for a Learn turn.

The path id is the storage key the tutor reads/writes learner state for a
turn.  It belongs to ``mode.learn`` (it is how the mode scopes its own
store), so the implementation lives here rather than in a legacy capability.

The metadata key is kept as ``mastery_path_id`` because that is the
programmatic contract shared with the frontend and the session snapshot —
the legacy *name* survives only as a wire/storage key, never as an internal
product abstraction.
"""

from __future__ import annotations

import re
from typing import Any

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_path_id(raw: str) -> str:
    """Make *raw* a safe storage key (matches the store's path guard)."""
    cleaned = _UNSAFE_ID_CHARS.sub("_", raw).strip("_")
    return cleaned or "default"


def resolve_learn_path_id(context: Any) -> str:
    """Resolve which learner path a turn operates on.

    Prefers an explicit ``mastery_path_id`` set by the frontend (so the tutor
    and the build wizard / dashboard agree on one storage key), then a book
    reference, then the session id for an ad-hoc path built inside a chat.
    """
    metadata = getattr(context, "metadata", None) or {}
    explicit = str(metadata.get("mastery_path_id") or "").strip()
    if explicit:
        return sanitize_path_id(explicit)
    refs = metadata.get("book_references", [])
    if refs:
        ref = refs[0]
        if isinstance(ref, str) and ref.strip():
            return sanitize_path_id(ref)
        if isinstance(ref, dict):
            candidate = str(ref.get("book_id") or ref.get("id") or "").strip()
            if candidate:
                return sanitize_path_id(candidate)
    return sanitize_path_id(str(getattr(context, "session_id", None) or "default"))


__all__ = ["resolve_learn_path_id", "sanitize_path_id"]

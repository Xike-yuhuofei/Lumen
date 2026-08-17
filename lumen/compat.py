"""Legacy ``mastery_path`` compatibility mapping (Phase 5).

The legacy capability name is kept only as a compatibility entry at the
transport/orchestration boundary.  Internally, ``mode.learn`` is the only
learn abstraction; this module translates old names into it.
"""

from __future__ import annotations


def resolve_learn_mode(capability: str | None) -> str | None:
    """Map a requested capability name onto the canonical learn mode.

    ``"mastery_path"`` (and ``"mastery"``) are accepted for backward
    compatibility and rewritten to ``"mode.learn"``.  Everything else is
    returned unchanged.
    """
    if capability in ("mastery_path", "mastery"):
        return "mode.learn"
    return capability
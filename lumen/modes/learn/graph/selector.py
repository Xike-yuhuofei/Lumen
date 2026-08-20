"""Explicit selection of the Teaching Graph Candidate vs. the teaching-hook path.

The candidate is a *bake-off* controller: it must coexist with and be clearly
distinguishable from the existing teaching-hook path so a later A/B / offline
bake-off can compare them on identical inputs.  It lives in ``mode.learn`` and
defaults to **off** — the production Learn turn keeps its exact previous
behaviour unless explicitly enabled.
"""

from __future__ import annotations

import os

#: Opt-in env switch.  Set to ``1`` / ``true`` to route Learn turns through the
#: Teaching Session Graph Candidate instead of the teaching-hook path.  Unset is
#: the production (hook) behaviour.
LUMEN_LEARN_GRAPH_CANDIDATE_ENV = "LUMEN_LEARN_GRAPH_CANDIDATE"


def is_graph_candidate_enabled() -> bool:
    """Whether the Teaching Session Graph Candidate is selected for this process."""
    return os.environ.get(LUMEN_LEARN_GRAPH_CANDIDATE_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def route_learn_turn(*, context) -> str:
    """Choose the orchestration route for a Learn turn.

    Returns ``"graph"`` when the candidate is enabled (and this is a Learn
    turn); otherwise ``"hook"`` (the existing teaching-hook path).
    """
    is_learn = bool(getattr(getattr(context, "metadata", None), "get", lambda *a: False)(
        "mastery_mode", False
    ))
    return "graph" if (is_learn and is_graph_candidate_enabled()) else "hook"


__all__ = [
    "LUMEN_LEARN_GRAPH_CANDIDATE_ENV",
    "is_graph_candidate_enabled",
    "route_learn_turn",
]
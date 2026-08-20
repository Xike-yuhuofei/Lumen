"""Selection of the Learn teaching control path.

The **Teaching Session Graph** is the production default — and, since Candidate A
(teaching-hook + generic Agent Loop) was retired, the **only** Learn teaching
control path.  There is no legacy/fallback switch: Learn turns always run through
the graph.  This module keeps a minimal routing contract for the orchestrator and
for tests so the graph's primacy is explicit and auditable.

The selector is a pure ``mode.learn`` controller: it only decides *whether* this
is a Learn turn, never *how* the Agent Runtime (a mode-agnostic dependency)
executes a turn.
"""

from __future__ import annotations


def is_graph_candidate_enabled() -> bool:
    """Whether the Teaching Session Graph is the active Learn control path.

    The graph is the sole production Learn teaching path, so this is always
    ``True`` (no legacy fallback exists).
    """
    return True


def route_learn_turn(*, context) -> str:
    """Choose the orchestration route for a Learn turn.

    Returns ``"graph"`` (Teaching Session Graph) for Learn turns.  Non-Learn
    turns return ``"hook"`` (a no-op route kept for the generic path's contract;
    it is never selected for Learn turns).
    """
    is_learn = bool(getattr(getattr(context, "metadata", None), "get", lambda *a: False)(
        "mastery_mode", False
    ))
    return "graph" if is_learn else "hook"


__all__ = [
    "is_graph_candidate_enabled",
    "route_learn_turn",
]
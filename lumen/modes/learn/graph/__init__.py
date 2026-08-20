"""Teaching Session Graph — ``mode.learn``-owned educational orchestration.

This package is the **production default** Learn teaching architecture.  It
drives Learn Mode through an explicit teaching flow (a Teaching Session Graph)
instead of the LLM autonomously calling teaching tools to decide the main path.
It is strictly a ``mode.learn`` orchestration layer:

* Teaching Session Graph  — owns pedagogical orchestration + teaching state
  transition (this package).
* Agent Runtime           — keeps LLM / Tools / Streaming / Usage / Budget /
  durable Start-Resume-Retry; the graph only *calls* it (never re-implements it).
* Learner Domain          — the single authority for long-term learner state;
  every authoritative write still funnels through the Domain Commit Foundation.

The Teaching Architecture Promotion (see ``ARCHITECTURE_V1.md`` §6) made this
the **PRODUCTION DEFAULT** and retired Candidate A (teaching-hook + generic
Agent Loop): there is no legacy/fallback switch — Learn turns always run through
the graph.
"""

from lumen.modes.learn.graph.contract import (
    CANDIDATE_POLICY_VERSION,
    Lineage,
    PolicyDecision,
    TeachingNode,
    TeachRunOutcome,
)
from lumen.modes.learn.graph.selector import (
    is_graph_candidate_enabled,
    route_learn_turn,
)

__all__ = [
    "Lineage",
    "PolicyDecision",
    "TeachRunOutcome",
    "TeachingNode",
    "CANDIDATE_POLICY_VERSION",
    "is_graph_candidate_enabled",
    "route_learn_turn",
]
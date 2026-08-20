"""Minimal Teaching Session Graph Candidate — ``mode.learn``-owned educational
orchestration.

This package is the *Candidate* that proves Learn Mode can be driven by an
explicit teaching flow (a Teaching Session Graph) instead of the LLM
autonomously calling teaching tools to decide the main path.  It is strictly a
``mode.learn`` orchestration layer:

* Teaching Session Graph  — owns pedagogical orchestration + teaching state
  transition (this package).
* Agent Runtime           — keeps LLM / Tools / Streaming / Usage / Budget /
  durable Start-Resume-Retry; the graph only *calls* it (never re-implements it).
* Learner Domain          — the single authority for long-term learner state;
  every authoritative write still funnels through the Domain Commit Foundation.

Candidate is **retained as an Experimental / Research Asset** (default off),
frozen by the Teaching Architecture decision (KEEP A, see ``ARCHITECTURE_V1.md``
§6): the Teaching Architecture Experiment is CLOSED and Candidate B is not a
pending-promotion candidate.  It stays opt-in via
``LUMEN_LEARN_GRAPH_CANDIDATE=1`` for experiment, research and future needs.
"""

from lumen.modes.learn.graph.contract import (
    CANDIDATE_POLICY_VERSION,
    Lineage,
    PolicyDecision,
    TeachingNode,
    TeachRunOutcome,
)
from lumen.modes.learn.graph.selector import (
    LUMEN_LEARN_GRAPH_CANDIDATE_ENV,
    is_graph_candidate_enabled,
    route_learn_turn,
)

__all__ = [
    "Lineage",
    "PolicyDecision",
    "TeachRunOutcome",
    "TeachingNode",
    "CANDIDATE_POLICY_VERSION",
    "LUMEN_LEARN_GRAPH_CANDIDATE_ENV",
    "is_graph_candidate_enabled",
    "route_learn_turn",
]
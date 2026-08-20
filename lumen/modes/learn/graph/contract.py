"""Contracts for the Minimal Teaching Session Graph Candidate.

These are the *public seams* of the candidate graph: the enumerated nodes of
the closed loop, the immutable PolicyDecision the graph commits, and the stable
``teaching_session_id -> decision_id -> action_id -> evidence_id -> commit_id``
lineage that proves every learner effect is auditable end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Version tag the candidate stamps onto every decision it commits.  Bump when
#: the policy stack / reducer changes so stale decisions can be re-derived.
CANDIDATE_POLICY_VERSION = "teaching-engine:v1"


class TeachingNode(str, Enum):
    """The nodes of the minimal teaching closed loop (explicit, auditable).

    The graph walks these deterministically per execution; the *order* is the
    pedagogical control flow (as opposed to the LLM deciding it indirectly
    through teaching tools).
    """

    SNAPSHOT = "snapshot"          # fresh read of the authoritative learner aggregate
    ASSESS = "assess"              # grade an incoming answer / project current evidence
    DIAGNOSE = "diagnose"          # classify the assessment (correct/misconception/mastery/due)
    DECIDE = "decide"              # explicit PolicyDecision from the Teaching Engine
    ACT = "act"                    # execute the decided TeachingAction (poses or generates)
    COMMIT = "commit"              # authoritative DomainCommit of any evidence/results
    CONTINUE = "continue"          # loop back for the next decision
    TERMINATE = "terminate"        # COMPLETE / terminal stop


#: The concrete topology of the minimal loop.  ``COMMIT`` (when it produced tea-
#: ching evidence) branches on whether the goal is reached.
GRAPH_TOPOLOGY: dict[str, tuple[str, ...]] = {
    TeachingNode.SNAPSHOT.value: (TeachingNode.ASSESS.value,),
    TeachingNode.ASSESS.value: (TeachingNode.DIAGNOSE.value,),
    TeachingNode.DIAGNOSE.value: (TeachingNode.DECIDE.value,),
    TeachingNode.DECIDE.value: (TeachingNode.ACT.value,),
    TeachingNode.ACT.value: (TeachingNode.COMMIT.value, TeachingNode.CONTINUE.value),
    TeachingNode.COMMIT.value: (TeachingNode.CONTINUE.value, TeachingNode.TERMINATE.value),
    TeachingNode.CONTINUE.value: (TeachingNode.DECIDE.value, TeachingNode.TERMINATE.value),
    TeachingNode.TERMINATE.value: (),
}


@dataclass(frozen=True)
class Lineage:
    """The stable, persisted identity chain for one learner effect.

    ``decision_id`` is minted by the graph (never by the LLM); the following ids
    are all *derived* so a crash/resume cannot fork them::

        teaching_session_id ─► ┌ decision_id ─► action_id ─► evidence_id(s) ─► commit_id(s)
        execution_generation ─┘

    ``execution_generation`` (the durable Agent Runtime thread) and
    ``teaching_session_id`` are tracked at the edges; the domain line runs
    through the middle column.  They are never conflated.
    """

    teaching_session_id: str
    execution_generation: str
    decision_id: str = ""
    action_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    commit_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "teaching_session_id": self.teaching_session_id,
            "execution_generation": self.execution_generation,
            "decision_id": self.decision_id,
            "action_id": self.action_id,
            "evidence_ids": list(self.evidence_ids),
            "commit_ids": list(self.commit_ids),
        }


@dataclass
class PolicyDecision:
    """An immutable, audit-able decision the graph committed.

    Mirrors the reducer's ``decision`` payload (see
    :meth:`DomainCommitService._decision_payload`): the deterministic teaching
    action plus trace + version so the "why this is taught next" is replayable.
    """

    decision_id: str
    policy_version: str = CANDIDATE_POLICY_VERSION
    action: str = ""
    focus_node_id: str = ""
    strategy: str = ""
    reason: str = ""
    policy_applied: str = ""
    trace: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """The serialisable payload committed verbatim as the decision."""
        return {
            "decision_id": self.decision_id,
            "policy_version": self.policy_version,
            "action": self.action,
            "focus_node_id": self.focus_node_id,
            "strategy": self.strategy,
            "reason": self.reason,
            "policy_applied": self.policy_applied,
            "trace": self.trace,
        }


@dataclass
class TeachRunOutcome:
    """What one graph run decided + did, so callers and tests can audit it."""

    node: TeachingNode
    decision: PolicyDecision
    lineage: Lineage
    is_terminal: bool = False
    committed: bool | None = None   # None == no domain effect this run
    posed_pending: bool = False     # an open question is now awaiting an answer
    graded: bool = False            # an incoming answer was graded this run
    feedback: str = ""


__all__ = [
    "CANDIDATE_POLICY_VERSION",
    "TeachingNode",
    "GRAPH_TOPOLOGY",
    "Lineage",
    "PolicyDecision",
    "TeachRunOutcome",
]
"""DomainCommit contracts for the Learner Domain.

The commit contract is the single, authoritative way to mutate a learner
aggregate. A :class:`DomainCommitRequest` expresses *intent* (evidence to
append, a proposed state snapshot, outbox projections); it never gets to
blindly overwrite authoritative derived state — the canonical reducer
(:mod:`lumen.modes.learn.commit.reducers`) recomputes mastery from the
evidence ledger and the repository performs optimistic-concurrency (CAS).

Correctness model: ``at-least-once execution + idempotent atomic domain
commit + optimistic concurrency``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommitStatus(str, Enum):
    """Persisted / returned status of a domain commit.

    * APPLIED                 — expected == actual: fast path.
    * APPLIED_RECONCILED      — version conflict resolved inside the tx:
      evidence accepted, stale derived state rejected, reducer rebuilt state.
    * REPLAYED                — response for an already-committed action (the
      stored receipt is returned; not a new row).
    * CONFLICT_REDECISION_REQUIRED — a strict, non-mergeable command whose
      conflict cannot be safely reconciled; no authoritative state changed.
    """

    APPLIED = "APPLIED"
    APPLIED_RECONCILED = "APPLIED_RECONCILED"
    REPLAYED = "REPLAYED"
    CONFLICT_REDECISION_REQUIRED = "CONFLICT_REDECISION_REQUIRED"


class CommitError(Exception):
    """Base class for commit-layer errors."""


class IdempotencyKeyReuse(CommitError):
    """The same ``action_id`` was reused with a different payload.

    The original domain effect stands; nothing further is written.
    """


class StoreBusy(CommitError):
    """SQLite returned ``database is locked`` / busy; retry the same action."""


class InvalidCommit(CommitError):
    """The request was structurally invalid (no evidence, bad payload, …)."""


class RestartRequired(CommitError):
    """Recovery of the learner db requires a clean restart (integrity)."""


@dataclass
class Evidence:
    """One raw, append-only observation to append to ``assessment_evidence``.

    ``outcome_json`` holds the assessment result (e.g. ``{"is_correct": …}``);
    ``raw_response_json`` holds the learner's original answer / explanation.
    Both must be present; a bare mastery score is not a valid outcome.

    ``evaluator_kind`` is one of ``deterministic`` / ``human`` / ``llm``;
    ``evaluator_version`` is required so qualitative judgements carry
    provenance (rubric / model version) and can never be a naked boolean.
    """

    target_type: str  # knowledge_point / objective / path
    target_id: str
    evidence_type: str  # quiz_answer / feynman_explanation / review_answer / …
    outcome: bool
    raw_response: str = ""
    outcome_json: dict[str, Any] = field(default_factory=dict)
    raw_response_json: dict[str, Any] = field(default_factory=dict)
    evaluator_kind: str = "deterministic"
    evaluator_version: str = "v1"
    policy_version: str = ""
    observed_at_ms: int = 0
    recorded_at_ms: int = 0
    session_id: str = ""
    turn_id: str = ""
    decision_id: str = ""
    supersedes_evidence_id: str = ""
    ordinal: int = 0


@dataclass
class OutboxIntent:
    """A cross-storage projection intent committed atomically with the learner.

    P0 only honours ``destination="question_bank"`` (the notebook read-model).
    """

    destination: str = "question_bank"
    event_type: str = "attempt_upsert"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainCommitRequest:
    """The intent to atomically mutate one learner aggregate."""

    learner_id: str
    action_id: str
    expected_learner_version: int
    proposed_state: dict[str, Any]  # full LearningProgress payload (intent)
    evidence: list[Evidence] = field(default_factory=list)
    decision: dict[str, Any] | None = None  # immutable PolicyDecision payload
    decision_id: str = ""
    outbox: list[OutboxIntent] = field(default_factory=list)
    # ``strict`` conflicts are never silently reconciled (P0 does not use them
    # for assessment — those always reconcile). Reserved for future commands.
    strict: bool = False


@dataclass
class DomainCommitReceipt:
    """Auditable result of a commit; persisted verbatim in ``domain_commits``."""

    commit_id: str
    action_id: str
    learner_id: str
    status: CommitStatus
    expected_version: int
    actual_base_version: int
    resulting_version: int
    evidence_ids: list[str] = field(default_factory=list)
    emitted_event_ids: list[str] = field(default_factory=list)
    outbox_event_ids: list[str] = field(default_factory=list)
    decision_stale: bool = False
    requires_redecision: bool = False
    committed_at_ms: int = 0
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_id": self.commit_id,
            "action_id": self.action_id,
            "learner_id": self.learner_id,
            "status": self.status.value,
            "expected_version": self.expected_version,
            "actual_base_version": self.actual_base_version,
            "resulting_version": self.resulting_version,
            "evidence_ids": list(self.evidence_ids),
            "emitted_event_ids": list(self.emitted_event_ids),
            "outbox_event_ids": list(self.outbox_event_ids),
            "decision_stale": self.decision_stale,
            "requires_redecision": self.requires_redecision,
            "committed_at_ms": self.committed_at_ms,
            "replayed": self.replayed,
        }


__all__ = [
    "CommitStatus",
    "CommitError",
    "IdempotencyKeyReuse",
    "StoreBusy",
    "InvalidCommit",
    "RestartRequired",
    "Evidence",
    "OutboxIntent",
    "DomainCommitRequest",
    "DomainCommitReceipt",
]
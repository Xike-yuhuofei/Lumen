"""Learner Domain Commit Foundation (P0).

Establish the ``at-least-once execution + idempotent atomic domain commit +
optimistic concurrency`` correctness model for the Learner Domain.

Ownership: ``mode.learn``. This package never reaches into Runtime
implementations; it owns ``learner.db`` and exposes the atomic commit path,
canonical reducers, JSON migration and the question-bank transactional outbox.
"""

from lumen.modes.learn.commit.contract import (
    CommitError,
    CommitStatus,
    DomainCommitReceipt,
    DomainCommitRequest,
    Evidence,
    IdempotencyKeyReuse,
    InvalidCommit,
    OutboxIntent,
    StoreBusy,
)
from lumen.modes.learn.commit.identity import (
    commit_id,
    evidence_id,
    new_uuid4,
    stable_hash,
)
from lumen.modes.learn.commit.repository import LearnerDomainRepository

# DomainCommitService is imported lazily/deferred name bindings are avoided so
# importing the package does not drag the full stack into module load.

__all__ = [
    "CommitError",
    "CommitStatus",
    "DomainCommitReceipt",
    "DomainCommitRequest",
    "Evidence",
    "IdempotencyKeyReuse",
    "InvalidCommit",
    "OutboxIntent",
    "StoreBusy",
    "LearnerDomainRepository",
    "commit_id",
    "evidence_id",
    "new_uuid4",
    "stable_hash",
]
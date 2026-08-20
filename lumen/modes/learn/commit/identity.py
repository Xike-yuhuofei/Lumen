"""Stable identity and hashing for the Learner Domain commit foundation.

Every authoritative Learner-Domain object gets a stable, deterministic id so
``at-least-once`` retries collapse to ``effectively-once`` without a separate
durable checkpoint:

* ``action_id``   — one UUIDv4 per teaching action that may produce evidence or
  a domain effect; for the P0 funnel the service derives it deterministically
  from the immutable attempt content so a tool retry reuses the same id.
* ``evidence_id`` — ``UUIDv5(EVIDENCE_NS, f"{learner_id}:{action_id}:{ordinal}")``.
* ``commit_id``   — ``UUIDv5(COMMIT_NS, f"{learner_id}:{action_id}")``; one
  commit per (learner, action) is the idempotency boundary.
* ``legacy_*``    — stable ids for JSON-migrated attempts.

Uniqueness is *ultimately* enforced by SQLite UNIQUE constraints
(``UNIQUE(learner_id, action_id, ordinal)`` and ``UNIQUE(learner_id, action_id)``);
these ids only make it deterministic across replays.
"""

from __future__ import annotations

import hashlib
import json
import uuid

# Fixed version-5 namespaces (arbitrary but stable — never change these).
LEGACY_NAMESPACE_V1 = uuid.UUID("9a2d4c6e-1f3b-4c8a-b5d7-0e6a2c9d4f11")
EVIDENCE_NAMESPACE_V1 = uuid.UUID("8c1e7a3d-5b2f-4d9e-a6c4-3f0d8b7e6a22")
COMMIT_NAMESPACE_V1 = uuid.UUID("6f4b2d8e-9c1a-4e5f-b3d7-1a2c4e6f8a33")


def new_uuid4() -> str:
    """A fresh, unique action/decision id."""
    return str(uuid.uuid4())


def evidence_id(learner_id: str, action_id: str, ordinal: int) -> str:
    """Deterministic evidence id for (learner, action, ordinal).

    Re-computable on replay so a crash between assessment and checkpoint
    cannot fork the evidence id.
    """
    return str(
        uuid.uuid5(EVIDENCE_NAMESPACE_V1, f"{learner_id}:{action_id}:{ordinal}")
    )


def commit_id(learner_id: str, action_id: str) -> str:
    """One commit id per (learner, action) — the idempotency boundary."""
    return str(uuid.uuid5(COMMIT_NAMESPACE_V1, f"{learner_id}:{action_id}"))


def legacy_action_id(learner_id: str, *, index: int, payload_hash: str) -> str:
    """Stable action id for a JSON-migrated legacy attempt.

    Uses ``index + payload_hash`` (not just the question id) so repeated
    ``feynman:{kp}`` attempts and identical-looking records stay distinct.
    """
    return str(
        uuid.uuid5(
            LEGACY_NAMESPACE_V1, f"legacy:{learner_id}:attempt:{index}:{payload_hash}"
        )
    )


def legacy_evidence_id(learner_id: str, action_id: str) -> str:
    """Evidence id for a legacy attempt (ordinal 0)."""
    return evidence_id(learner_id, action_id, 0)


def stable_hash(obj: object) -> str:
    """A stable sha256 of any JSON-serialisable object.

    Dictionaries are sorted and separators are compacted so equal content
    produces an identical hash regardless of key order or whitespace.
    """
    payload = json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, dict)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # defensive; not a supported path
            pass
    if hasattr(value, "__dict__"):
        return {
            key: val for key, val in vars(value).items() if not key.startswith("_")
        }
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def ensure_no_path_traversal(value: str, what: str = "learner_id") -> None:
    """Reject learner ids / action ids that could escape the storage boundary."""
    if not value or value != value.strip():
        raise ValueError(f"Invalid {what} (empty or whitespace)")
    if any(ch in value for ch in ("/", "\\", "..", ":")):
        raise ValueError(f"Invalid {what}: {value!r}")


__all__ = [
    "LEGACY_NAMESPACE_V1",
    "EVIDENCE_NAMESPACE_V1",
    "COMMIT_NAMESPACE_V1",
    "new_uuid4",
    "evidence_id",
    "commit_id",
    "legacy_action_id",
    "legacy_evidence_id",
    "stable_hash",
    "ensure_no_path_traversal",
]
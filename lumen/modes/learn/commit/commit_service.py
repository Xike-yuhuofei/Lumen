"""DomainCommitService — the atomic, idempotent, optimistic-concurrency write
path for the Learner Domain.

A single ``commit()`` runs *everything* for one action inside one ``learner.db``
transaction:

1. idempotency lookup (replay original receipt, or reject key reuse);
2. immutable ``policy_decisions`` insert + hash verify;
3. ``assessment_evidence`` append (idempotent) + hash verify;
4. read the current aggregate version/state;
5. CAS fast path or in-transaction conflict reconciliation;
6. canonical reducer (ignores any caller mastery snapshot);
7. ``UPDATE learner_aggregates ... WHERE learner_version = :actual``;
8. ``learner_events`` (+ stale ``policy_decision_events`` on conflict);
9. ``domain_commits`` receipt;
10. ``outbox_events``.

LLM / agent-runtime / question-bank writes / stream emits are *never* inside
this transaction (see :mod:`lumen.modes.learn.commit.outbox` for the projected
side effect).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from lumen.modes.learn.commit.constants import EVIDENCE_SCHEMA_VERSION
from lumen.modes.learn.commit.contract import (
    CommitStatus,
    DomainCommitReceipt,
    DomainCommitRequest,
    Evidence,
    IdempotencyKeyReuse,
    InvalidCommit,
    StoreBusy,
)
from lumen.modes.learn.commit.identity import (
    commit_id as _commit_id,
)
from lumen.modes.learn.commit.identity import (
    ensure_no_path_traversal,
    new_uuid4,
    stable_hash,
)
from lumen.modes.learn.commit.identity import (
    evidence_id as _evidence_id,
)
from lumen.modes.learn.commit.reducers import REDUCER_VERSION, reduce_state
from lumen.modes.learn.commit.repository import (
    LearnerDomainRepository,
    now_ms,
    rows_to_evidence_dicts,
)
from lumen.shared._util.observability import span as telemetry_span

logger = logging.getLogger(__name__)


def _evidence_payload(ev: Evidence) -> dict[str, Any]:
    return {
        "target_type": ev.target_type,
        "target_id": ev.target_id,
        "evidence_type": ev.evidence_type,
        "outcome_json": ev.outcome_json or {"is_correct": bool(ev.outcome)},
        "raw_response_json": ev.raw_response_json or {"user_answer": ev.raw_response or ""},
        "evaluator_kind": ev.evaluator_kind,
        "evaluator_version": ev.evaluator_version,
        "policy_version": ev.policy_version,
        "observed_at_ms": ev.observed_at_ms,
        "session_id": ev.session_id,
        "turn_id": ev.turn_id,
    }


def build_request_hash(request: DomainCommitRequest) -> str:
    """Immutable intents that define the domain effect (never the derived state
    or its volatile version / timestamps)."""
    return stable_hash(
        {
            "decision": _decision_payload(request) if request.decision_id else None,
            "evidence": [_evidence_payload(ev) for ev in request.evidence],
            "outbox": [_outbox_payload(o) for o in request.outbox],
        }
    )


def _decision_payload(request: DomainCommitRequest) -> dict[str, Any]:
    return {
        "decision_id": request.decision_id,
        "payload": request.decision or {},
    }


def _outbox_payload(intent) -> dict[str, Any]:
    return {
        "destination": intent.destination,
        "event_type": intent.event_type,
        "payload": intent.payload,
    }


class DomainCommitService:
    """Transactional author of Learner Domain commits."""

    def __init__(self, repository: LearnerDomainRepository | None = None) -> None:
        self._repo = repository or LearnerDomainRepository()

    @property
    def repository(self) -> LearnerDomainRepository:
        return self._repo

    # ── public ──────────────────────────────────────────────────────────

    def commit(self, request: DomainCommitRequest) -> DomainCommitReceipt:
        ensure_no_path_traversal(request.learner_id)
        if not request.proposed_state:
            raise InvalidCommit("proposed_state is required")
        req_hash = build_request_hash(request)
        # One telemetry span per learner-domain commit: the state-transition
        # outcome (committed / replayed / error) is observable directly.
        with telemetry_span(
            "teaching_commit",
            kind="teaching",
            attrs={"learner_id": request.learner_id, "action_id": request.action_id},
            metric="teaching_commit",
        ) as sp:
            try:
                with self._repo.tx():
                    receipt = self._commit_in_tx(request, req_hash)
                sp.attrs["commit_status"] = str(getattr(receipt.status, "value", receipt.status))
                return receipt
            except sqlite3.OperationalError as exc:  # database is locked / busy
                msg = str(exc).lower()
                if "locked" in msg or "busy" in msg:
                    raise StoreBusy("learner.db is busy; retry the same action_id") from exc
                raise

    def replay(self, learner_id: str, action_id: str) -> DomainCommitReceipt | None:
        """Return the stored receipt for an already-committed action (``None``
        if the action was never committed). Safe to call at any time."""
        row = self._repo.get_commit(learner_id, action_id)
        if row is None:
            return None
        return _receipt_from_row(row, replayed=True, status=CommitStatus.REPLAYED)

    # ── transaction body ────────────────────────────────────────────────

    def _commit_in_tx(self, request: DomainCommitRequest, req_hash: str) -> DomainCommitReceipt:
        learner = request.learner_id
        action = request.action_id
        commit_id = _commit_id(learner, action)
        ts = now_ms()
        evidence_ids: list[str] = []

        # 1. Idempotency: same (learner, action) already committed?
        existing = self._repo.get_commit(learner, action)
        if existing is not None:
            if existing["request_hash"] == req_hash:
                return _receipt_from_row(existing, replayed=True, status=CommitStatus.REPLAYED)
            raise IdempotencyKeyReuse(
                f"action_id {action!r} reused with a different payload for learner {learner!r}"
            )

        # Read the current aggregate up-front; for a brand-new learner create a
        # placeholder row at version 0 so evidence FK references hold, then the
        # CAS update below promotes it to ``resulting``.
        agg = self._repo.get_aggregate(learner)
        if agg is None:
            actual_version = 0
            base_state: dict[str, Any] | None = None
            self._repo.insert_aggregate(
                learner_id=learner,
                new_version=0,
                state_json=_json(request.proposed_state),
                state_hash=stable_hash(request.proposed_state),
                commit_id=commit_id,
                now_ms=ts,
            )
        else:
            actual_version = int(agg["learner_version"])
            base_state = _loads(agg["state_json"])

        # 2. Immutable decision.
        if request.decision_id:
            decision_hash = stable_hash(request.decision or {})
            self._repo.insert_policy_decision(
                {
                    "decision_id": request.decision_id,
                    "learner_id": learner,
                    "input_learner_version": request.expected_learner_version,
                    "policy_version": (request.decision or {}).get("policy_version", ""),
                    "evidence_ids_json": _json(
                        [e_id for e_id in (evidence_ids)]
                    ),
                    "decision_json": _json(request.decision or {}),
                    "decision_hash": decision_hash,
                    "created_at_ms": ts,
                }
            )
            stored = self._repo.get_policy_decision_hash(request.decision_id)
            if stored is not None and stored != decision_hash:
                raise InvalidCommit(
                    f"decision_id {request.decision_id!r} reused with different payload"
                )

        # 3. Evidence append (idempotent) + verify.
        for ordinal, ev in enumerate(request.evidence):
            ev_id = _evidence_id(learner, action, ordinal)
            payload = _evidence_payload(ev)
            self._repo.insert_evidence(
                {
                    "evidence_id": ev_id,
                    "learner_id": learner,
                    "action_id": action,
                    "ordinal": ordinal,
                    "decision_id": request.decision_id or None,
                    "session_id": ev.session_id,
                    "turn_id": ev.turn_id,
                    "target_type": ev.target_type,
                    "target_id": ev.target_id,
                    "evidence_type": ev.evidence_type,
                    "assessment_id": "",
                    "outcome_json": _json(payload["outcome_json"]),
                    "raw_response_json": _json(payload["raw_response_json"]),
                    "evaluator_kind": ev.evaluator_kind,
                    "evaluator_version": ev.evaluator_version,
                    "policy_version": ev.policy_version,
                    "observed_at_ms": ev.observed_at_ms,
                    "recorded_at_ms": ev.recorded_at_ms or ts,
                    "supersedes_evidence_id": ev.supersedes_evidence_id or None,
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "payload_hash": stable_hash(payload),
                }
            )
            evidence_ids.append(ev_id)

        # Verify every appended evidence row's payload hash matches intent.
        for row in self._repo.get_evidence_payloads_for_action(learner, action):
            target = next(
                (ev for o, ev in enumerate(request.evidence) if o == row["ordinal"]),
                None,
            )
            if target is not None:
                expected = stable_hash(_evidence_payload(target))
                if row["payload_hash"] != expected:
                    raise InvalidCommit(
                        f"evidence ordinal {row['ordinal']} has a mismatched payload hash"
                    )

        # 4-6. Read current aggregate, reconcile, reduce.
        ledger = rows_to_evidence_dicts(self._repo.get_evidence_ledger(learner))
        fast = request.expected_learner_version == actual_version
        new_state = reduce_state(
            base=base_state,
            proposed=dict(request.proposed_state),
            ledger=ledger,
            reconcile=not fast,
        )
        resulting = actual_version + 1
        state_json = _json(new_state)
        state_hash = stable_hash(new_state)

        # 7. CAS hard guard (aggregate row already exists from step 2/prep).
        changed = self._repo.upsert_aggregate(
            learner_id=learner,
            actual_version=actual_version,
            new_version=resulting,
            state_json=state_json,
            state_hash=state_hash,
            commit_id=commit_id,
            now_ms=ts,
        )
        if changed != 1:
            raise StoreBusy("CAS lost update; retry the same action_id")

        # 8. Commit receipt row (must precede learner_events / outbox, which FK
        #    reference domain_commits).
        decision_stale = False
        if not fast and request.decision_id:
            decision_stale = True
        running_version = resulting
        receipt = DomainCommitReceipt(
            commit_id=commit_id,
            action_id=action,
            learner_id=learner,
            status=CommitStatus.APPLIED_RECONCILED if not fast else CommitStatus.APPLIED,
            expected_version=request.expected_learner_version,
            actual_base_version=actual_version,
            resulting_version=running_version,
            evidence_ids=evidence_ids,
            emitted_event_ids=[],  # filled after the event is written
            decision_stale=decision_stale,
            requires_redecision=decision_stale,
            committed_at_ms=ts,
        )
        self._repo.insert_commit(
            {
                "commit_id": commit_id,
                "learner_id": learner,
                "action_id": action,
                "decision_id": request.decision_id or None,
                "expected_learner_version": request.expected_learner_version,
                "actual_base_version": actual_version,
                "resulting_learner_version": running_version,
                "status": receipt.status.value,
                "request_hash": req_hash,
                "receipt_json": _json(receipt.to_dict()),
                "committed_at_ms": ts,
            }
        )

        # 9. Audit event(s).
        event_id = new_uuid4()
        event_type = "mastery_update" if evidence_ids else "state_update"
        self._repo.insert_learner_event(
            {
                "event_id": event_id,
                "learner_id": learner,
                "learner_version": resulting,
                "commit_id": commit_id,
                "ordinal": 0,
                "event_type": event_type,
                "payload_json": _json(
                    {
                        "status": "APPLIED_RECONCILED" if not fast else "APPLIED",
                        "reducer_version": REDUCER_VERSION,
                    }
                ),
                "evidence_ids_json": _json(evidence_ids),
                "reducer_version": REDUCER_VERSION,
                "created_at_ms": ts,
            }
        )
        receipt.emitted_event_ids = [event_id]

        # 10. Policy stale event on conflict.
        if not fast and request.decision_id:
            self._repo.insert_policy_decision_event(
                {
                    "event_id": new_uuid4(),
                    "decision_id": request.decision_id,
                    "kind": "stale",
                    "reason_json": _json(
                        {
                            "expected": request.expected_learner_version,
                            "actual": actual_version,
                        }
                    ),
                    "caused_by_commit_id": commit_id,
                    "created_at_ms": ts,
                }
            )

        # 11. Outbox.
        outbox_event_ids: list[str] = []
        for intent in request.outbox:
            oid = new_uuid4()
            self._repo.insert_outbox(
                {
                    "event_id": oid,
                    "commit_id": commit_id,
                    "destination": intent.destination,
                    "event_type": intent.event_type,
                    "payload_json": _json(intent.payload),
                    "payload_hash": stable_hash(intent.payload),
                    "attempts": 0,
                    "available_at_ms": ts,
                    "delivered_at_ms": None,
                    "last_error": "",
                    "created_at_ms": ts,
                }
            )
            outbox_event_ids.append(oid)
        receipt.outbox_event_ids = outbox_event_ids
        return receipt

    # ── last-aggregate snapshot (for tests / diagnostics) ───────────────

    def get_state(self, learner_id: str) -> dict[str, Any] | None:
        agg = self._repo.get_aggregate(learner_id)
        return _loads(agg["state_json"]) if agg else None


def _receipt_from_row(
    row, *, replayed: bool, status: CommitStatus | None = None
) -> DomainCommitReceipt:
    data = _loads(row["receipt_json"]) or {}
    return DomainCommitReceipt(
        commit_id=data.get("commit_id", ""),
        action_id=data.get("action_id", ""),
        learner_id=data.get("learner_id", ""),
        status=status or (data.get("status") or CommitStatus.APPLIED),
        expected_version=int(data.get("expected_version", 0)),
        actual_base_version=int(data.get("actual_base_version", 0)),
        resulting_version=int(data.get("resulting_version", 0)),
        evidence_ids=list(data.get("evidence_ids", [])),
        emitted_event_ids=list(data.get("emitted_event_ids", [])),
        outbox_event_ids=list(data.get("outbox_event_ids", [])),
        decision_stale=bool(data.get("decision_stale")),
        requires_redecision=bool(data.get("requires_redecision")),
        committed_at_ms=int(data.get("committed_at_ms", 0)),
        replayed=replayed,
    )


def _json(obj: Any) -> str:
    import json as _json_mod

    return _json_mod.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(text: str | None) -> Any:
    import json as _json_mod

    if not text:
        return None
    try:
        return _json_mod.loads(text)
    except Exception:
        return None


__all__ = ["DomainCommitService", "build_request_hash"]
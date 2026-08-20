"""Learner Domain SQLite repository.

``mode.learn`` owns this schema and its single authority: ``learner.db``
(located at ``data/user/workspace/learning/`` by default, injectable for
tests). Evidence, derived state, policy decisions, events, commit receipts and
the transactional outbox share one SQLite transaction boundary.

Explicit run configuration per connection:
``PRAGMA foreign_keys=ON; journal_mode=WAL; synchronous=FULL;
busy_timeout=5000``.

Write transactions use ``BEGIN IMMEDIATE`` so writers queue up front, then an
``UPDATE ... WHERE learner_version = :actual`` performs the CAS hard guard.

This class is transport/persistence-only. ``mode.learn`` never reuses the
Runtime ``SQLiteSessionStore`` class and learner tables are never placed in
``chat_history.db``.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time

from lumen.modes.learn.commit.constants import STATE_SCHEMA_VERSION

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS learner_aggregates (
    learner_id          TEXT PRIMARY KEY,
    learner_version     INTEGER NOT NULL CHECK (learner_version >= 0),
    state_schema_version INTEGER NOT NULL,
    state_json          TEXT NOT NULL,
    state_hash          TEXT NOT NULL,
    last_commit_id      TEXT NOT NULL DEFAULT '',
    created_at_ms       INTEGER NOT NULL,
    updated_at_ms       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_evidence (
    evidence_seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id          TEXT NOT NULL UNIQUE,
    learner_id           TEXT NOT NULL REFERENCES learner_aggregates(learner_id) ON DELETE CASCADE,
    action_id            TEXT NOT NULL,
    ordinal              INTEGER NOT NULL CHECK (ordinal >= 0),
    decision_id           TEXT,
    session_id            TEXT NOT NULL DEFAULT '',
    turn_id               TEXT NOT NULL DEFAULT '',
    target_type           TEXT NOT NULL,
    target_id             TEXT NOT NULL,
    evidence_type         TEXT NOT NULL,
    assessment_id         TEXT NOT NULL DEFAULT '',
    outcome_json          TEXT NOT NULL,
    raw_response_json     TEXT NOT NULL,
    evaluator_kind        TEXT NOT NULL,
    evaluator_version     TEXT NOT NULL,
    policy_version        TEXT NOT NULL DEFAULT '',
    observed_at_ms        INTEGER NOT NULL,
    recorded_at_ms        INTEGER NOT NULL,
    supersedes_evidence_id TEXT,
    schema_version        INTEGER NOT NULL,
    payload_hash          TEXT NOT NULL,
    UNIQUE (learner_id, action_id, ordinal)
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    decision_id              TEXT PRIMARY KEY,
    learner_id               TEXT NOT NULL,
    input_learner_version     INTEGER NOT NULL,
    policy_version            TEXT NOT NULL,
    evidence_ids_json         TEXT NOT NULL,
    decision_json             TEXT NOT NULL,
    decision_hash             TEXT NOT NULL,
    created_at_ms             INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decision_events (
    event_id          TEXT PRIMARY KEY,
    decision_id       TEXT NOT NULL REFERENCES policy_decisions(decision_id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    reason_json       TEXT NOT NULL,
    caused_by_commit_id TEXT NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    UNIQUE (decision_id, kind, caused_by_commit_id)
);

CREATE TABLE IF NOT EXISTS domain_commits (
    commit_id                    TEXT PRIMARY KEY,
    learner_id                   TEXT NOT NULL REFERENCES learner_aggregates(learner_id) ON DELETE CASCADE,
    action_id                    TEXT NOT NULL,
    decision_id                  TEXT,
    expected_learner_version     INTEGER NOT NULL,
    actual_base_version          INTEGER NOT NULL,
    resulting_learner_version    INTEGER NOT NULL,
    status                       TEXT NOT NULL,
    request_hash                 TEXT NOT NULL,
    receipt_json                 TEXT NOT NULL,
    committed_at_ms              INTEGER NOT NULL,
    UNIQUE (learner_id, action_id),
    UNIQUE (learner_id, resulting_learner_version)
);

CREATE TABLE IF NOT EXISTS learner_events (
    event_id          TEXT PRIMARY KEY,
    learner_id        TEXT NOT NULL REFERENCES learner_aggregates(learner_id) ON DELETE CASCADE,
    learner_version   INTEGER NOT NULL,
    commit_id         TEXT NOT NULL REFERENCES domain_commits(commit_id) ON DELETE CASCADE,
    ordinal           INTEGER NOT NULL,
    event_type        TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    reducer_version   TEXT NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    UNIQUE (commit_id, ordinal),
    UNIQUE (learner_id, learner_version, ordinal)
);

CREATE TABLE IF NOT EXISTS outbox_events (
    event_id          TEXT PRIMARY KEY,
    commit_id         TEXT NOT NULL REFERENCES domain_commits(commit_id) ON DELETE CASCADE,
    destination       TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    payload_hash      TEXT NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0,
    available_at_ms   INTEGER NOT NULL,
    delivered_at_ms   INTEGER,
    last_error        TEXT NOT NULL DEFAULT '',
    created_at_ms     INTEGER NOT NULL,
    UNIQUE (commit_id, destination, event_type)
);

CREATE TABLE IF NOT EXISTS migration_log (
    migration_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id     TEXT NOT NULL UNIQUE,
    source_path    TEXT NOT NULL,
    source_hash    TEXT NOT NULL,
    state_hash     TEXT NOT NULL,
    schema_variant TEXT NOT NULL DEFAULT '',
    imported_at    REAL NOT NULL,
    result         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_learner_seq
    ON assessment_evidence (learner_id, evidence_seq);
CREATE INDEX IF NOT EXISTS idx_commits_learner
    ON domain_commits (learner_id, action_id);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox_events (delivered_at_ms, created_at_ms);
"""


class LearnerDomainRepository:
    """SQLite backing for the Learner Domain commit foundation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else default_learner_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._connect()
        self._init_schema()

    # ── connection / pragmas ────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        if str(self._db_path) != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:  # pragma: no cover - env dependent
                pass
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_DDL)
            self._conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── transaction boundary ────────────────────────────────────────────

    def tx(self):
        """Yield inside an explicit ``BEGIN IMMEDIATE`` … COMMIT/ROLLBACK."""

        class _Tx:
            def __init__(self, repo: LearnerDomainRepository) -> None:
                self._repo = repo

            def __enter__(self) -> LearnerDomainRepository:
                self._repo._lock.acquire()
                try:
                    self._repo._conn.execute("BEGIN IMMEDIATE")
                except Exception:
                    self._repo._lock.release()
                    raise
                return self._repo

            def __exit__(self, exc_type, exc, tb) -> bool:
                try:
                    if exc_type is None:
                        self._repo._conn.commit()
                    else:
                        self._repo._conn.rollback()
                finally:
                    self._repo._lock.release()
                return False

        return _Tx(self)

    def integrity_ok(self) -> bool:
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")

    # ── low-level row accessors (call inside a tx for writes) ───────────

    def get_commit(self, learner_id: str, action_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT request_hash, receipt_json, committed_at_ms, status "
            "FROM domain_commits WHERE learner_id = ? AND action_id = ?",
            (learner_id, action_id),
        ).fetchone()

    def get_aggregate(self, learner_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT learner_version, state_json, state_hash, last_commit_id, "
            "state_schema_version FROM learner_aggregates WHERE learner_id = ?",
            (learner_id,),
        ).fetchone()

    def get_evidence_ledger(self, learner_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM assessment_evidence WHERE learner_id = ? "
            "ORDER BY evidence_seq ASC",
            (learner_id,),
        ).fetchall()

    def insert_evidence(self, cols: dict) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO assessment_evidence (
                evidence_id, learner_id, action_id, ordinal, decision_id,
                session_id, turn_id, target_type, target_id, evidence_type,
                assessment_id, outcome_json, raw_response_json, evaluator_kind,
                evaluator_version, policy_version, observed_at_ms, recorded_at_ms,
                supersedes_evidence_id, schema_version, payload_hash
            ) VALUES (
                :evidence_id, :learner_id, :action_id, :ordinal, :decision_id,
                :session_id, :turn_id, :target_type, :target_id, :evidence_type,
                :assessment_id, :outcome_json, :raw_response_json, :evaluator_kind,
                :evaluator_version, :policy_version, :observed_at_ms, :recorded_at_ms,
                :supersedes_evidence_id, :schema_version, :payload_hash
            )
            ON CONFLICT(learner_id, action_id, ordinal) DO NOTHING
            """,
            cols,
        )
        return cur.rowcount

    def get_evidence_payloads_for_action(self, learner_id: str, action_id: str) -> list:
        return self._conn.execute(
            "SELECT ordinal, payload_hash FROM assessment_evidence "
            "WHERE learner_id = ? AND action_id = ?",
            (learner_id, action_id),
        ).fetchall()

    def insert_policy_decision(self, cols: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO policy_decisions (
                decision_id, learner_id, input_learner_version, policy_version,
                evidence_ids_json, decision_json, decision_hash, created_at_ms
            ) VALUES (
                :decision_id, :learner_id, :input_learner_version, :policy_version,
                :evidence_ids_json, :decision_json, :decision_hash, :created_at_ms
            )
            ON CONFLICT(decision_id) DO NOTHING
            """,
            cols,
        )

    def get_policy_decision_hash(self, decision_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT decision_hash FROM policy_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        return row["decision_hash"] if row else None

    def get_policy_decision(self, decision_id: str) -> sqlite3.Row | None:
        """Read an immutable, committed decision verbatim (Decision Replay).

        Never re-runs the policy: this is a pure read of the authoritative
        ``policy_decisions`` ledger so a historical decision can be reused /
        audited without touching the learner authority.
        """
        return self._conn.execute(
            "SELECT decision_json, decision_hash, policy_version, "
            "input_learner_version FROM policy_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()

    def insert_policy_decision_event(self, cols: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO policy_decision_events (
                event_id, decision_id, kind, reason_json, caused_by_commit_id, created_at_ms
            ) VALUES (
                :event_id, :decision_id, :kind, :reason_json,
                :caused_by_commit_id, :created_at_ms
            )
            ON CONFLICT(decision_id, kind, caused_by_commit_id) DO NOTHING
            """,
            cols,
        )

    def upsert_aggregate(
        self,
        *,
        learner_id: str,
        actual_version: int,
        new_version: int,
        state_json: str,
        state_hash: str,
        commit_id: str,
        now_ms: int,
    ) -> int:
        """CAS update; returns affected rowcount (1 for success, 0 for lost)."""
        cur = self._conn.execute(
            """
            UPDATE learner_aggregates SET
                learner_version = :nv,
                state_json = :state,
                state_hash = :hash,
                last_commit_id = :commit,
                updated_at_ms = :now
            WHERE learner_id = :id AND learner_version = :av
            """,
            {
                "nv": new_version,
                "state": state_json,
                "hash": state_hash,
                "commit": commit_id,
                "now": now_ms,
                "id": learner_id,
                "av": actual_version,
            },
        )
        return cur.rowcount

    def insert_aggregate(
        self,
        *,
        learner_id: str,
        new_version: int,
        state_json: str,
        state_hash: str,
        commit_id: str,
        now_ms: int,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO learner_aggregates (
                learner_id, learner_version, state_schema_version, state_json,
                state_hash, last_commit_id, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(learner_id) DO NOTHING
            """,
            (
                learner_id,
                new_version,
                STATE_SCHEMA_VERSION,
                state_json,
                state_hash,
                commit_id,
                now_ms,
                now_ms,
            ),
        )
        return cur.rowcount

    def insert_commit(self, cols: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO domain_commits (
                commit_id, learner_id, action_id, decision_id,
                expected_learner_version, actual_base_version,
                resulting_learner_version, status, request_hash, receipt_json,
                committed_at_ms
            ) VALUES (
                :commit_id, :learner_id, :action_id, :decision_id,
                :expected_learner_version, :actual_base_version,
                :resulting_learner_version, :status, :request_hash, :receipt_json,
                :committed_at_ms
            )
            ON CONFLICT(learner_id, action_id) DO NOTHING
            """,
            cols,
        )

    def insert_learner_event(self, cols: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO learner_events (
                event_id, learner_id, learner_version, commit_id, ordinal,
                event_type, payload_json, evidence_ids_json, reducer_version,
                created_at_ms
            ) VALUES (
                :event_id, :learner_id, :learner_version, :commit_id, :ordinal,
                :event_type, :payload_json, :evidence_ids_json, :reducer_version,
                :created_at_ms
            )
            ON CONFLICT(learner_id, learner_version, ordinal) DO NOTHING
            """,
            cols,
        )

    def insert_outbox(self, cols: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO outbox_events (
                event_id, commit_id, destination, event_type, payload_json,
                payload_hash, attempts, available_at_ms, delivered_at_ms,
                last_error, created_at_ms
            ) VALUES (
                :event_id, :commit_id, :destination, :event_type, :payload_json,
                :payload_hash, :attempts, :available_at_ms, :delivered_at_ms,
                :last_error, :created_at_ms
            )
            ON CONFLICT(commit_id, destination, event_type) DO NOTHING
            """,
            cols,
        )

    # ── outbox reads / writes ───────────────────────────────────────────

    def pending_outbox(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM outbox_events WHERE delivered_at_ms IS NULL "
            "ORDER BY created_at_ms ASC LIMIT ?",
            (limit,),
        ).fetchall()

    def outbox_row(self, event_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM outbox_events WHERE event_id = ?", (event_id,)
        ).fetchone()

    def mark_outbox_delivered(self, event_id: str, now_ms: int) -> None:
        self._conn.execute(
            "UPDATE outbox_events SET delivered_at_ms = ? WHERE event_id = ?",
            (now_ms, event_id),
        )

    def mark_outbox_error(self, event_id: str, error: str, attempts: int) -> None:
        self._conn.execute(
            "UPDATE outbox_events SET last_error = ?, attempts = ? WHERE event_id = ?",
            (error, attempts, event_id),
        )

    # ── aggregate-level convenience (used by the LegacyStore facade) ────

    def list_learner_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT learner_id FROM learner_aggregates ORDER BY learner_id"
        ).fetchall()
        return [row["learner_id"] for row in rows]

    def delete_aggregate(self, learner_id: str) -> None:
        with self.tx():
            # Evidence / commits / events / outbox cascade via FK.
            self._conn.execute(
                "DELETE FROM policy_decisions WHERE learner_id = ?", (learner_id,)
            )
            self._conn.execute(
                "DELETE FROM migration_log WHERE learner_id = ?", (learner_id,)
            )
            self._conn.execute(
                "DELETE FROM learner_aggregates WHERE learner_id = ?", (learner_id,)
            )

    def exists(self, learner_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM learner_aggregates WHERE learner_id = ?", (learner_id,)
            ).fetchone()
            is not None
        )

    def current_version(self, learner_id: str) -> int | None:
        row = self.get_aggregate(learner_id)
        return row["learner_version"] if row else None

    def mark_migrated(self, entry: dict) -> None:
        self._conn.execute(
            """
            INSERT INTO migration_log (
                learner_id, source_path, source_hash, state_hash, schema_variant,
                imported_at, result
            ) VALUES (
                :learner_id, :source_path, :source_hash, :state_hash, :schema_variant,
                :imported_at, :result
            )
            ON CONFLICT(learner_id) DO NOTHING
            """,
            entry,
        )

    def migrated_learner_ids(self) -> set[str]:
        return {
            row["learner_id"]
            for row in self._conn.execute("SELECT learner_id FROM migration_log").fetchall()
        }


def default_learner_db_path() -> Path:
    from lumen.shared._util.runtime_paths import get_path_service

    return get_path_service().get_workspace_dir() / "learning" / "learner.db"


def rows_to_evidence_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    out = []
    for row in rows:
        d = dict(row)
        d["outcome_json"] = json.loads(d["outcome_json"] or "{}")
        d["raw_response_json"] = json.loads(d["raw_response_json"] or "{}")
        out.append(d)
    return out


def now_ms() -> int:
    return int(time.time() * 1000)


__all__ = ["LearnerDomainRepository", "default_learner_db_path", "rows_to_evidence_dicts", "now_ms"]
"""Durable graph-node checkpoint for the Teaching Session Graph Candidate.

Ownership boundary (kept separate, never blurred):

* This store holds ONLY Teaching Session *execution* state — which node of the
  teaching loop the graph last reached for a given Agent Runtime execution and
  the learner version it decided against.  It is physically separate from the
  Learner Domain ``learner.db`` and from the Agent Runtime checkpoint DB.
* It is NOT the authoritative LearnerState — correctness never depends on it.
  The graph re-derives the decision from a *fresh* snapshot each run and relies
  on idempotent DomainCommits for replay; this store is purely for auditability
  and for re-entering the loop at the right node after a restart.

A restart recovers ``teaching_session_id -> execution_generation -> last node``
from disk, so "which step am I on" never needs in-memory guesswork.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from lumen.modes.learn.teaching_session import _default_root

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teaching_graph_nodes (
    teaching_session_id TEXT NOT NULL,
    execution_generation TEXT NOT NULL,
    last_node TEXT NOT NULL,
    learner_version INTEGER NOT NULL DEFAULT 0,
    decision_id TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (teaching_session_id, execution_generation)
);
"""


class TeachingGraphCheckpoint:
    """Persist the last walking position of the teaching graph per execution."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "teaching_graph_checkpoint.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def record(
        self,
        *,
        teaching_session_id: str,
        execution_generation: str,
        last_node: str,
        learner_version: int = 0,
        decision_id: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO teaching_graph_nodes"
                " (teaching_session_id, execution_generation, last_node,"
                "  learner_version, decision_id, updated_at_ms)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(teaching_session_id, execution_generation) DO UPDATE SET"
                "  last_node = excluded.last_node,"
                "  learner_version = excluded.learner_version,"
                "  decision_id = excluded.decision_id,"
                "  updated_at_ms = excluded.updated_at_ms",
                (
                    teaching_session_id,
                    execution_generation,
                    last_node,
                    learner_version,
                    decision_id,
                    int(time.time() * 1000),
                ),
            )
            self._conn.commit()

    def position(
        self, teaching_session_id: str, execution_generation: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM teaching_graph_nodes"
                " WHERE teaching_session_id = ? AND execution_generation = ?",
                (teaching_session_id, execution_generation),
            ).fetchone()
        return dict(row) if row is not None else None


__all__ = ["TeachingGraphCheckpoint"]
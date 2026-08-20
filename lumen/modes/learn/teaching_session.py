"""Teaching Session ↔ Agent Runtime execution identity / lifecycle governor.

This is the ``mode.learn``-owned orchestration layer that lets one Teaching
Session weave through *several* independent Agent Runtime executions and durably
recover that relationship across a process restart.  It deliberately keeps the
three identities distinct:

* ``teaching_session_id``  — the stable, persisted identity of a teaching session
  (looked up by ``path_id``).  It is NEVER the LangGraph ``thread_id``.
* ``execution_generation / thread_id`` — the identity of ONE Agent Runtime durable
  execution (LangGraph thread, lives in ``LumenSqliteCheckpointer``).  It
  survives ``start → crash → restart → resume`` and changes on ``retry`` /
  ``create-next``.
* ``decision_id / action_id / commit_id`` — Learner Domain lineage, owned by the
  Domain Commit Foundation.  This governor never reads or writes that lineage.

Ownership boundaries (kept separate, never blurred):
* LangGraph checkpoint  = provider execution state  → ``LumenSqliteCheckpointer``
* Teaching Session → execution map, lifecycle position  → this store
* Learner authoritative write  → Domain Commit (mode.learn ``LearningStore``)

A crash can leave an execution ``ACTIVE`` (the process died before recording a
termination).  On restart the governor treats ``ACTIVE``/``INTERRUPTED`` as
*resumable* — it reissues ``resume`` on the SAME ``execution_generation`` and lets
LangGraph continue from the durable checkpoint (idempotent, no completed node
re-run, no lost side effect).  A terminal state (``completed`` / ``failed`` /
``cancelled``) means the next user turn starts a NEW execution (``create-next``).
An explicit ``retry`` forges a brand-new, isolated execution identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid

from lumen.shared._util.runtime_paths import get_path_service

#: Terminal states for which a fresh user turn must NOT auto-resume the same
#: execution; the governor instead creates the NEXT execution.
_TERMINAL_STATES = ("completed", "failed", "cancelled")
#: States that are resumable: the persisted execution may still hold an
#: incomplete checkpoint (interrupted, or the process crashed mid-run).
_RESUMABLE_STATES = ("active", "interrupted")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teaching_sessions (
    teaching_session_id TEXT PRIMARY KEY,
    path_id TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    current_execution_generation TEXT,
    current_status TEXT NOT NULL DEFAULT 'none'
);
CREATE TABLE IF NOT EXISTS teaching_session_executions (
    teaching_session_id TEXT NOT NULL,
    execution_generation TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (teaching_session_id, execution_generation)
);
CREATE INDEX IF NOT EXISTS idx_executions_session
    ON teaching_session_executions (teaching_session_id, created_at_ms);
"""


class ExecutionStatus(str, Enum):
    """Lifecycle state of one Agent Runtime execution within a session."""

    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def map_termination_to_status(*, operation: str, completed: bool, termination: str) -> ExecutionStatus:
    """Classify an adapter-reported termination into a lifecycle status.

    * ``interrupted``  → ``INTERRUPTED`` (resumable by the next turn)
    * forced stop (budget / step / tool limit) → ``COMPLETED`` (terminal output;
      the next user turn starts a fresh execution)
    * ``cancelled``    → ``CANCELLED``
    * otherwise not completed / error → ``FAILED``
    * completed        → ``COMPLETED``
    """
    if completed:
        return ExecutionStatus.COMPLETED
    if termination == "interrupted":
        return ExecutionStatus.INTERRUPTED
    if termination == "cancelled":
        return ExecutionStatus.CANCELLED
    # A forced stop (budget / step / tool limit) still carries terminal output:
    # the session treats it as done — the next user turn starts a fresh execution.
    if termination in ("budget_exhausted", "step_limit", "tool_limit"):
        return ExecutionStatus.COMPLETED
    return ExecutionStatus.FAILED


@dataclass
class ExecutionPlan:
    """What the governor decided for the next Agent Runtime execution."""

    teaching_session_id: str
    operation: str  # start | resume | retry
    execution_generation: str
    resume_input: str | None = None
    #: When ``retry`` or ``create-next`` mints a fresh identity, the execution
    #: it replaces (empty for the first execution of a session).
    superseded: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "teaching_session_id": self.teaching_session_id,
            "operation": self.operation,
            "execution_generation": self.execution_generation,
            "resume_input": self.resume_input,
            "superseded": self.superseded,
        }


def new_execution_generation() -> str:
    """A fresh, globally unique Agent Runtime execution identity (never re-used)."""
    return f"exec-{uuid.uuid4().hex[:16]}"


class TeachingSessionGovernor:
    """Persistent Teaching Session → execution registry + lifecycle planning.

    Durable on disk (SQLite) so a restart recovers the session → execution map
    and current position without guessing from in-memory state.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "teaching_sessions.db"
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

    # ── session identity ───────────────────────────────────────────────

    def ensure_session(self, path_id: str, *, session_id: str | None = None) -> str:
        """Look up (or create) a stable Teaching Session for ``path_id``.

        ``teaching_session_id`` is stable across restarts and is independent of
        every ``execution_generation``.  If ``session_id`` is provided it is
        honoured (idempotent), else a fresh id is minted on first registration.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT teaching_session_id FROM teaching_sessions WHERE path_id = ?",
                (path_id,),
            ).fetchone()
            if row is not None:
                return str(row["teaching_session_id"])
            sid = session_id or f"ts-{uuid.uuid4().hex[:16]}"
            self._conn.execute(
                "INSERT INTO teaching_sessions"
                " (teaching_session_id, path_id, created_at_ms,"
                "  current_execution_generation, current_status)"
                " VALUES (?, ?, ?, NULL, 'none')",
                (sid, path_id, _now_ms()),
            )
            self._conn.commit()
            return sid

    def session_by_id(self, teaching_session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM teaching_sessions WHERE teaching_session_id = ?",
                (teaching_session_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    # ── lifecycle planning ─────────────────────────────────────────────

    def plan(
        self,
        teaching_session_id: str,
        *,
        retry: bool = False,
        resume_input: str | None = None,
    ) -> ExecutionPlan:
        """Decide the next execution: resume / start (create-next) / retry.

        * ``retry`` → forget a NEW execution identity, isolated from the current
          one (the replaced identity is recorded on ``superseded``).
        * current execution is ``active``/``interrupted`` → ``resume`` it (same
          ``execution_generation``, LangGraph continues from its checkpoint).
        * otherwise (no execution yet, or a terminal state) → a NEW ``start``
          (create-next) identity.
        """
        session = self.session_by_id(teaching_session_id)
        if session is None:
            raise ValueError(f"unknown teaching session: {teaching_session_id!r}")
        if retry:
            superseded = session.get("current_execution_generation") or ""
            return ExecutionPlan(
                teaching_session_id=teaching_session_id,
                operation="retry",
                execution_generation=new_execution_generation(),
                resume_input=resume_input,
                superseded=superseded,
            )
        current = session.get("current_execution_generation")
        status = session.get("current_status") or "none"
        if current and status in _RESUMABLE_STATES:
            return ExecutionPlan(
                teaching_session_id=teaching_session_id,
                operation="resume",
                execution_generation=str(current),
                resume_input=resume_input,
            )
        superseded = str(current or "")
        return ExecutionPlan(
            teaching_session_id=teaching_session_id,
            operation="start",
            execution_generation=new_execution_generation(),
            resume_input=resume_input,
            superseded=superseded,
        )

    # ── record ─────────────────────────────────────────────────────────

    def record_start(self, plan: ExecutionPlan) -> None:
        """Persist that ``plan.execution_generation`` is now the active one."""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO teaching_session_executions"
                " (teaching_session_id, execution_generation, operation, status,"
                "  created_at_ms, updated_at_ms)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan.teaching_session_id,
                    plan.execution_generation,
                    plan.operation,
                    ExecutionStatus.ACTIVE.value,
                    _now_ms(),
                    _now_ms(),
                ),
            )
            self._conn.execute(
                "UPDATE teaching_sessions"
                " SET current_execution_generation = ?, current_status = ?"
                " WHERE teaching_session_id = ?",
                (plan.execution_generation, ExecutionStatus.ACTIVE.value, plan.teaching_session_id),
            )
            self._conn.commit()

    def record_termination(
        self,
        teaching_session_id: str,
        execution_generation: str,
        status: ExecutionStatus,
    ) -> None:
        """Persist how the execution ended; advances the session's current position."""
        with self._lock:
            self._conn.execute(
                "UPDATE teaching_session_executions SET status = ?, updated_at_ms = ?"
                " WHERE teaching_session_id = ? AND execution_generation = ?",
                (status.value, _now_ms(), teaching_session_id, execution_generation),
            )
            self._conn.execute(
                "UPDATE teaching_sessions SET current_status = ?"
                " WHERE teaching_session_id = ?",
                (status.value, teaching_session_id),
            )
            self._conn.commit()

    def rebase_execution(
        self,
        teaching_session_id: str,
        planned_generation: str,
        actual_generation: str,
    ) -> None:
        """Re-point the execution row / session cursor to the ACTUAL runtime
        identity.

        The Agent Runtime (P1 provider) forges its own fresh identity on
        ``retry`` (it drops the caller-supplied generation for isolation), so the
        planned generation can differ from the real LangGraph thread recorded by
        the adapter.  When they diverge we move the planned row and the session's
        current pointer to the actual identity so the session → execution map
        always points at the real durable thread.
        """
        if not actual_generation or actual_generation == planned_generation:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE teaching_session_executions SET execution_generation = ?"
                " WHERE teaching_session_id = ? AND execution_generation = ?",
                (actual_generation, teaching_session_id, planned_generation),
            )
            self._conn.execute(
                "UPDATE teaching_sessions SET current_execution_generation = ?"
                " WHERE teaching_session_id = ? AND current_execution_generation = ?",
                (actual_generation, teaching_session_id, planned_generation),
            )
            self._conn.commit()

    def executions(self, teaching_session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM teaching_session_executions WHERE teaching_session_id = ?"
                " ORDER BY created_at_ms ASC",
                (teaching_session_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def _default_root() -> Path:
    # A mode.learn-owned directory, physically separate from the Learner Domain
    # DB (learner.db) and from the Agent Runtime checkpoint DB, so the three
    # ownerships never share a file.
    return get_path_service().get_workspace_dir() / "teaching_session"


def _now_ms() -> int:
    return int(time.time() * 1000)


__all__ = [
    "ExecutionStatus",
    "ExecutionPlan",
    "TeachingSessionGovernor",
    "map_termination_to_status",
    "new_execution_generation",
]
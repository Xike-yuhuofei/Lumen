"""Transactional outbox for Learner Domain → question-bank projection.

The authority is ``learner.db``; the target read-model is
``chat_history.db.notebook_entries``. Outbox rows are written atomically with
the source commit (so a projection can be detected, recovered and replayed),
but delivered asynchronously by an in-process dispatcher — never inside the
learner commit transaction, and never in a way that can roll back an
authoritative evidence commit.

Target idempotency: a small ``question_bank_sync_receipts`` addendum table in
``chat_history.db`` keys delivery by ``source_event_id`` (the outbox event id)
+ ``payload_hash``. Replay collapses to no-op; a reused id with a different
hash is a hard failure (never a silent overwrite).
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import time
from typing import Any

from lumen.modes.learn.commit.repository import LearnerDomainRepository, now_ms

logger = logging.getLogger(__name__)

_RECEIPTS_DDL = """
CREATE TABLE IF NOT EXISTS question_bank_sync_receipts (
    source_event_id TEXT PRIMARY KEY,
    payload_hash    TEXT NOT NULL,
    delivered_at    REAL NOT NULL
);
"""


class OutboxPayloadConflict(Exception):
    """Same outbox event id reused with a different payload hash."""


class OutboxSessionGone(Exception):
    """Target notebook write failed because the session no longer exists
    (durable/permanent — surfaced, never silently retried forever)."""


class OutboxDispatcher:
    """In-process dispatcher for pending ``learner.db`` outbox events."""

    def __init__(
        self,
        repository: LearnerDomainRepository | None = None,
        chat_db_path: Path | str | None = None,
    ) -> None:
        self._repo = repository or LearnerDomainRepository()
        self._chat_path = Path(chat_db_path) if chat_db_path else None

    def _resolve_chat_path(self) -> Path:
        """The question-bank target db — where the runtime session store points
        (so monkeypatched/injected session stores in tests are honoured)."""
        if self._chat_path is not None:
            return self._chat_path
        try:
            from lumen.runtime.session import get_sqlite_session_store

            store = get_sqlite_session_store()
            if store is not None and getattr(store, "db_path", None):
                return Path(store.db_path)
        except Exception:  # noqa: BLE001 - fall back to the default layout
            pass
        return _default_chat_db_path()

    def pending(self, limit: int = 100) -> list:
        with self._repo.tx():
            return self._repo.pending_outbox(limit)

    def status(self, event_id: str) -> str:
        row = self._repo.outbox_row(event_id)
        if row is None:
            return "missing"
        if row["delivered_at_ms"] is not None:
            return "delivered"
        if row["last_error"]:
            return f"failed: {row['last_error']}"
        return "pending"

    def dispatch(self, limit: int = 10) -> dict[str, int]:
        """Dispatch up to ``limit`` pending events. Returns ``{ok, permanent_fail}``."""
        pending = self.pending(limit)
        stats = {"ok": 0, "retryable_fail": 0, "permanent_fail": 0}
        for event in pending:
            try:
                self._deliver(event)
                stats["ok"] += 1
            except OutboxSessionGone as exc:
                stats["permanent_fail"] += 1
                self._record_error(event["event_id"], str(exc))
                logger.warning("Permanent outbox failure for %s: %s", event["event_id"], exc)
            except Exception as exc:  # noqa: BLE001 - report, keep going
                stats["retryable_fail"] += 1
                self._record_error(event["event_id"], f"{type(exc).__name__}: {exc}")
                logger.warning("Outbox delivery failed for %s: %s", event["event_id"], exc)
        return stats

    # ── internals ───────────────────────────────────────────────────────

    def _deliver(self, event: sqlite3.Row) -> None:
        payload = _loads(event["payload_json"]) or {}
        payload_hash = event["payload_hash"]
        chat_path = self._resolve_chat_path()
        chat_path.parent.mkdir(parents=True, exist_ok=True)
        with _chat_conn(chat_path) as conn:
            conn.executescript(_RECEIPTS_DDL)
            rec = conn.execute(
                "SELECT payload_hash FROM question_bank_sync_receipts "
                "WHERE source_event_id = ?",
                (event["event_id"],),
            ).fetchone()
            if rec is not None:
                if rec["payload_hash"] != payload_hash:
                    raise OutboxPayloadConflict(
                        f"outbox event {event['event_id']} reused with different payload"
                    )
                # already delivered → nothing to project again.
            else:
                self._apply_to_notebook(conn, payload)
                conn.execute(
                    "INSERT INTO question_bank_sync_receipts (source_event_id, payload_hash, delivered_at)"
                    " VALUES (?, ?, ?)",
                    (event["event_id"], payload_hash, time.time()),
                )
        with self._repo.tx():
            self._repo.mark_outbox_delivered(event["event_id"], now_ms())

    def _apply_to_notebook(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return  # no session → nothing to project; mark delivered as no-op.
        if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise OutboxSessionGone(f"session {session_id!r} no longer exists")
        now = time.time()
        item = {
            "session_id": session_id,
            "turn_id": str(payload.get("turn_id") or ""),
            "question_id": str(payload.get("question_id") or ""),
            "question": str(payload.get("question") or ""),
            "question_type": str(payload.get("question_type") or "short_answer"),
            "options_json": _json(payload.get("options") or {}),
            "correct_answer": str(payload.get("correct_answer") or ""),
            "explanation": str(payload.get("explanation") or ""),
            "difficulty": str(payload.get("difficulty") or ""),
            "user_answer": str(payload.get("user_answer") or ""),
            "is_correct": 1 if payload.get("is_correct") else 0,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO notebook_entries (
                session_id, turn_id, question_id, question, question_type,
                options_json, correct_answer, explanation, difficulty,
                user_answer, user_answer_images_json, is_correct,
                bookmarked, followup_session_id, created_at, updated_at
            ) VALUES (
                :session_id, :turn_id, :question_id, :question, :question_type,
                :options_json, :correct_answer, :explanation, :difficulty,
                :user_answer, '[]', :is_correct, 0, '', :created_at, :updated_at
            )
            ON CONFLICT(session_id, turn_id, question_id) DO UPDATE SET
                user_answer = excluded.user_answer,
                is_correct = excluded.is_correct,
                updated_at = excluded.updated_at
            """,
            item,
        )

    def _record_error(self, event_id: str, error: str) -> None:
        with self._repo.tx():
            row = self._repo.outbox_row(event_id)
            attempts = int(row["attempts"]) + 1 if row is not None else 1
            self._repo.mark_outbox_error(event_id, error[:2000], attempts)


def _chat_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _default_chat_db_path() -> Path:
    from lumen.shared._util.runtime_paths import get_path_service

    return get_path_service().get_chat_history_db()


def _json(obj: Any) -> str:
    import json as _json_mod

    return _json_mod.dumps(obj, ensure_ascii=False)


def _loads(text: str | None) -> Any:
    import json as _json_mod

    if not text:
        return None
    try:
        return _json_mod.loads(text)
    except Exception:
        return None


__all__ = [
    "OutboxDispatcher",
    "OutboxPayloadConflict",
    "OutboxSessionGone",
]
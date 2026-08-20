"""Production durable async checkpointer for the P1 LangGraph provider.

Why this exists
---------------
The objective hardens durable resume into a first-class P1 runtime capability.
The ``langgraph-checkpoint-sqlite`` package released against
``langgraph-checkpoint==2.x`` (``AsyncSqliteSaver``) calls ``aiosqlite.Connection
.is_alive()``, which no released ``aiosqlite`` provides — so the *bundled* SQLite
backend is unusable in this environment. Rather than ship a monkeypatch shim, we
implement a real persistent async checkpointer on LangGraph's official
``BaseCheckpointSaver`` contract, backed by the stdlib ``sqlite3`` module (run in
a worker thread for async paths). LangGraph still owns checkpoint / resume /
dedup / interrupt semantics; this class only supplies durable storage — the
documented extension point ``compile(checkpointer=...)``.

It is durable (survives the process), NOT an in-memory saver, and requires no
aiosqlite dependency.
"""

from __future__ import annotations

import asyncio
import random
import sqlite3
import threading
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BLOB,
    metadata BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
"""


class LumenSqliteCheckpointer(BaseCheckpointSaver[str]):
    """Persistent, async-capable checkpointer over a local SQLite file.

    Use with ``compile(checkpointer=...)`` exactly like ``MemorySaver`` /
    ``AsyncSqliteSaver``. Durable across processes; no in-memory substitute.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        self.jsonplus_serde = JsonPlusSerializer()

    @property
    def db_path(self) -> Path:
        return self._path

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - idempotent
            pass

    def __enter__(self) -> LumenSqliteCheckpointer:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    async def __aenter__(self) -> LumenSqliteCheckpointer:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    # ── sync storage core ───────────────────────────────────────────────

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        _ = new_versions
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        type_, serialized = self.serde.dumps_typed(checkpoint)
        serialized_metadata = self.jsonplus_serde.dumps(
            get_checkpoint_metadata(config, metadata)
        )
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id,"
                " parent_checkpoint_id, type, checkpoint, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(thread_id),
                    checkpoint_ns,
                    checkpoint["id"],
                    config["configurable"].get("checkpoint_id"),
                    type_,
                    serialized,
                    serialized_metadata,
                ),
            )
            self._conn.commit()
        return {
            "configurable": {
                "thread_id": str(thread_id),
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        cid = get_checkpoint_id(config)
        with self._lock:
            if cid:
                row = self._conn.execute(
                    "SELECT * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ?"
                    " AND checkpoint_id = ?",
                    (str(thread_id), checkpoint_ns, cid),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ?"
                    " ORDER BY checkpoint_id DESC LIMIT 1",
                    (str(thread_id), checkpoint_ns),
                ).fetchone()
            if row is None:
                return None
            writes = self._conn.execute(
                "SELECT task_id, channel, type, value FROM writes WHERE thread_id = ?"
                " AND checkpoint_ns = ? AND checkpoint_id = ? ORDER BY task_id, idx",
                (str(row["thread_id"]), checkpoint_ns, str(row["checkpoint_id"])),
            ).fetchall()
        return _tuple_from_row(self, row, writes)

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM checkpoints ORDER BY checkpoint_id DESC"
            ).fetchall()
        if config:
            cid = get_checkpoint_id(config)
            rows = [
                r
                for r in rows
                if r["thread_id"] == config["configurable"]["thread_id"]
                and (not cid or str(r["checkpoint_id"]) == str(cid))
            ]
        if before:
            bc = get_checkpoint_id(before)
            rows = [r for r in rows if not bc or str(r["checkpoint_id"]) < str(bc)]
        n = limit if limit is not None else len(rows)
        return [_tuple_from_row(self, r, []) for r in rows[:n]]

    def put_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        _ = task_path
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self._lock:
            existing = {
                (r["task_id"], r["idx"])
                for r in self._conn.execute(
                    "SELECT task_id, idx FROM writes WHERE thread_id = ?"
                    " AND checkpoint_ns = ? AND checkpoint_id = ?",
                    (str(thread_id), checkpoint_ns, checkpoint_id),
                )
            }
            for idx, (channel, value) in enumerate(writes):
                w_idx = WRITES_IDX_MAP.get(channel, idx)
                if (task_id, w_idx) in existing:
                    continue
                type_, v = self.serde.dumps_typed(value)
                self._conn.execute(
                    "INSERT OR REPLACE INTO writes (thread_id, checkpoint_ns, checkpoint_id,"
                    " task_id, idx, channel, type, value) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(thread_id),
                        checkpoint_ns,
                        checkpoint_id,
                        task_id,
                        w_idx,
                        channel,
                        type_,
                        v,
                    ),
                )
            self._conn.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?", (str(thread_id),)
            )
            self._conn.execute(
                "DELETE FROM writes WHERE thread_id = ?", (str(thread_id),)
            )
            self._conn.commit()

    def get_next_version(self, current: str | None, channel: None) -> str:
        _ = channel
        base = 0
        if current:
            if isinstance(current, int):
                base = current
            else:
                base = int(str(current).split(".")[0])
        return f"{base + 1:032}.{random.random():016}"

    # ── async wrappers (LangGraph async path) ───────────────────────────

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        return await asyncio.to_thread(self.list, config, filter=filter, before=before, limit=limit)

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)


def _tuple_from_row(
    ckp: LumenSqliteCheckpointer, row: sqlite3.Row, writes: list[sqlite3.Row]
) -> CheckpointTuple:
    cconfig = {
        "configurable": {
            "thread_id": str(row["thread_id"]),
            "checkpoint_ns": str(row["checkpoint_ns"] or ""),
            "checkpoint_id": str(row["checkpoint_id"]),
        }
    }
    checkpoint = cast(Checkpoint, ckp.serde.loads_typed((row["type"], row["checkpoint"])))
    metadata = ckp.jsonplus_serde.loads(row["metadata"]) if row["metadata"] else {}
    parent = row["parent_checkpoint_id"]
    return CheckpointTuple(
        config=cconfig,
        checkpoint=checkpoint,
        metadata=cast(CheckpointMetadata, metadata),
        parent_config=(
            {
                "configurable": {
                    "thread_id": str(row["thread_id"]),
                    "checkpoint_ns": str(row["checkpoint_ns"] or ""),
                    "checkpoint_id": parent,
                }
            }
            if parent
            else None
        ),
        pending_writes=[
            (
                w["task_id"],
                w["channel"],
                ckp.serde.loads_typed((w["type"], w["value"])),
            )
            for w in writes
        ],
    )


__all__ = ["LumenSqliteCheckpointer"]
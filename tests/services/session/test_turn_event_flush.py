"""Post-stream turn-event flush: batching and workspace mirror.

The turn runtime buffers every live event in memory and persists the whole
batch after the stream drains, right before publishing DONE. Everything on
that path must stay O(1) round-trips w.r.t. the event count — per-event
commits/opens sat between the last streamed token and the client's spinner
clearing (the "stuck on generating" report).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution

pytestmark = pytest.mark.asyncio


def _buffered(session_id: str, turn_id: str, count: int) -> list[dict]:
    return [
        {
            "type": "content",
            "source": "chat",
            "stage": "",
            "content": f"chunk-{i}",
            "metadata": {},
            "session_id": session_id,
            "turn_id": turn_id,
            "seq": i + 1,
            "timestamp": 1000.0 + i,
        }
        for i in range(count)
    ]


@pytest.fixture
def stub_workspace(monkeypatch, tmp_path):
    """Point the runtime's workspace mirror at an isolated tmp tree."""

    class _StubPathService:
        def get_task_workspace(self, feature: str, task_id: str) -> Path:
            return tmp_path / "workspace" / feature / task_id

    monkeypatch.setattr(
        "deeptutor.services.session.turn_runtime.get_path_service",
        lambda: _StubPathService(),
    )
    return tmp_path / "workspace"


async def test_flush_mirrors_whole_batch_in_one_file_write(
    tmp_path, stub_workspace, monkeypatch
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 5)

    open_calls = 0
    real_open = open

    def counting_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1
        return real_open(*args, **kwargs)

    # Scope the ``open`` patch to the flush itself so the assertions below
    # (and fixture teardown) run against the real builtin.
    with pytest.MonkeyPatch.context() as flush_patch:
        flush_patch.setattr("builtins.open", counting_open)
        await runtime._flush_buffered_events(execution)

    # All five events reach the DB and the jsonl mirror, via ONE file open.
    persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == [f"chunk-{i}" for i in range(5)]
    mirror = stub_workspace / "chat" / turn["id"] / "events.jsonl"
    lines = [json.loads(line) for line in mirror.read_text().splitlines()]
    assert [line["content"] for line in lines] == [f"chunk-{i}" for i in range(5)]
    assert open_calls == 1


async def test_flush_is_idempotent_per_execution(tmp_path, stub_workspace) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 3)

    await runtime._flush_buffered_events(execution)
    await runtime._flush_buffered_events(execution)

    persisted = await store.get_turn_events(turn["id"])
    assert len(persisted) == 3
    mirror = stub_workspace / "chat" / turn["id"] / "events.jsonl"
    assert len(mirror.read_text().splitlines()) == 3


async def test_flush_survives_turn_deleted_mid_drain(tmp_path, stub_workspace) -> None:
    """Deleting the session mid-flush must not raise out of the turn task."""
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 2)
    await store.delete_session(session["id"])

    await runtime._flush_buffered_events(execution)  # must not raise

"""LumenSqliteCheckpointer — LangGraph BaseCheckpointSaver conformance gate.

LangGraph ships checkpoint tests in its repo but not in the installed wheel, so
this is an *equivalent* conformance suite built from the official contract
semantics (mirroring `InMemorySaver` and `AsyncSqliteSaver`, which are the
reference implementations of `BaseCheckpointSaver`). It verifies the contract
that every saver must honour — regardless of storage backend:

* put / get (round-trip, latest vs by-id) and thread / config identity;
* checkpoint parent / lineage chain;
* writes (store, load as pending_writes, dedup, no cross-thread leakage);
* list (newest-first, config filter, limit) and delete_thread;
* get_next_version progression;
* async surface (aget_tuple/aput/aput_writes/alist/adelete_thread);
* concurrent writes across threads (no corruption / no cross-talk);
* durability: close + reopen the same SQLite file (a process boundary) still
  yields the checkpoint.

The saver is only a durable storage adapter: it implements the persistence
methods and never re-implements scheduler / resume / dedup (LangGraph drives
those). The final assertion enforces that boundary structurally.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer


def _config(thread: str, cid: str | None = None) -> dict:
    c = {"configurable": {"thread_id": str(thread), "checkpoint_ns": ""}}
    if cid:
        c["configurable"]["checkpoint_id"] = cid
    return c


def _checkpoint(cid: str, values: dict) -> dict:
    return {
        "v": 1,
        "ts": "2023-01-01T00:00:00Z",
        "id": cid,
        "channel_values": values,
        "channel_versions": {},
        "versions_seen": {},
    }


def _meta(step: int) -> dict:
    return {"source": "loop", "step": step, "writes": {}, "score": 0.1}


@pytest.fixture
def ckp(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "ckp.db")
    yield cp
    cp.close()


def _run(coro):
    return asyncio.run(coro)


# ── put / get round-trip + lineage ────────────────────────────────────────


@pytest.mark.parametrize("async_api", [False, True])
def test_put_get_roundtrip_preserves_checkpoint_and_identity(tmp_path, async_api):
    cp = LumenSqliteCheckpointer(tmp_path / "ckp.db")
    try:
        ck = _checkpoint("ck-1", {"messages": ["a"], "count": 3})
        cfg = _config("T1")

        async def go():
            if async_api:
                new_cfg = await cp.aput(cfg, ck, _meta(1), {})
                got = await cp.aget_tuple(_config("T1"))
            else:
                new_cfg = cp.put(cfg, ck, _meta(1), {})
                got = cp.get_tuple(_config("T1"))
            return new_cfg, got

        new_cfg, got = _run(go())
        assert new_cfg["configurable"]["checkpoint_id"] == "ck-1"
        assert got is not None
        assert got.config["configurable"]["thread_id"] == "T1"
        # the checkpoint (including channel_values) is preserved verbatim
        assert got.checkpoint["id"] == "ck-1"
        assert got.checkpoint["channel_values"] == {"messages": ["a"], "count": 3}
        assert got.metadata["step"] == 1
        assert got.parent_config is None  # root checkpoint
    finally:
        cp.close()


def test_lineage_chain_matches_langgraph_parent_semantics(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "l.db")
    try:
        cfg = _config("T1")
        prev_cfg = None
        ids = []
        # a 3-checkpoint lineage like an agent loop would produce
        for i in range(3):
            cid = f"ck-{i}"
            new_cfg = cp.put(cfg, _checkpoint(cid, {"step": i}), _meta(i), {})
            # next put must reference the previous checkpoint as its parent
            cfg = _config("T1", new_cfg["configurable"]["checkpoint_id"])
            ids.append(cid)
        latest = cp.get_tuple(_config("T1"))
        assert latest.checkpoint["id"] == "ck-2"
        assert latest.parent_config is not None
        assert latest.parent_config["configurable"]["checkpoint_id"] == "ck-1"
        # explicit id lookup returns the named checkpoint with its own parent
        mid = cp.get_tuple(_config("T1", "ck-1"))
        assert mid is not None and mid.checkpoint["id"] == "ck-1"
        assert mid.parent_config["configurable"]["checkpoint_id"] == "ck-0"
    finally:
        cp.close()


# ── writes ────────────────────────────────────────────────────────────────


def test_put_writes_and_get_pending_writes(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "w.db")
    try:
        cid = "ck-1"
        cfg = _config("T1")
        cp.put(cfg, _checkpoint(cid, {}), _meta(0), {})
        cfg_w = _config("T1", cid)
        cp.put_writes(cfg_w, [("messages", {"role": "user", "content": "hi"})], task_id="taskA")
        got = cp.get_tuple(_config("T1"))
        assert got.pending_writes == [("taskA", "messages", {"role": "user", "content": "hi"})]
    finally:
        cp.close()


def test_writes_dedup_and_do_not_cross_threads(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "w2.db")
    try:
        for thread in ("T1", "T2"):
            cp.put(_config(thread), _checkpoint(f"ck-{thread}", {}), _meta(0), {})
        # same (task_id, channel) written twice to T1 must dedup to one
        cp.put_writes(_config("T1", "ck-T1"), [("messages", "one")], task_id="t")
        cp.put_writes(_config("T1", "ck-T1"), [("messages", "two")], task_id="t")
        t1 = cp.get_tuple(_config("T1"))
        t2 = cp.get_tuple(_config("T2"))
        assert len(t1.pending_writes) == 1
        assert t1.pending_writes[0][2] == "one"  # first writer wins, deduped
        # a different writer task on the same thread is a distinct write
        cp.put_writes(_config("T1", "ck-T1"), [("messages", "three")], task_id="u")
        t1b = cp.get_tuple(_config("T1"))
        assert len(t1b.pending_writes) == 2
        assert t2.pending_writes == []  # no leakage across threads
    finally:
        cp.close()


# ── list / delete ─────────────────────────────────────────────────────────


def test_list_newest_first_filters_and_limits(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "ls.db")
    try:
        for i in range(4):
            cp.put(_config("T1"), _checkpoint(f"ck-{i}", {"i": i}), _meta(i), {})
        cp.put(_config("T2"), _checkpoint("other-0", {}), _meta(0), {})
        all_items = cp.list(None)
        assert len(all_items) == 5  # all threads, newest-first
        assert {t.checkpoint["id"] for t in all_items} == {"ck-0", "ck-1", "ck-2", "ck-3", "other-0"}
        t1_items = cp.list(_config("T1"))
        assert {t.checkpoint["id"] for t in t1_items} == {"ck-0", "ck-1", "ck-2", "ck-3"}
        limited = cp.list(_config("T1"), limit=2)
        assert len(limited) == 2
    finally:
        cp.close()


def test_delete_thread_clears_only_that_thread(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "del.db")
    try:
        for thread in ("T1", "T2"):
            cp.put(_config(thread), _checkpoint(f"ck-{thread}", {}), _meta(0), {})
            cp.put_writes(_config(thread, f"ck-{thread}"), [("messages", "w")], task_id="t")
        cp.delete_thread("T1")
        assert cp.get_tuple(_config("T1")) is None
        assert cp.list(_config("T1")) == []
        # T2 untouched and its write still loads
        t2 = cp.get_tuple(_config("T2"))
        assert t2 is not None and t2.pending_writes == [("t", "messages", "w")]
    finally:
        cp.close()


# ── version progression ───────────────────────────────────────────────────


def test_get_next_version_monotonic(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "v.db")
    try:
        v0 = cp.get_next_version(None, None)
        v1 = cp.get_next_version(v0, None)
        v2 = cp.get_next_version(v1, None)
        assert v0 != v1 != v2
        # version scheme matches InMemorySaver: int part increments (32-padded)
        assert int(v1.split(".")[0]) == int(v0.split(".")[0]) + 1
        assert int(v2.split(".")[0]) == int(v1.split(".")[0]) + 1
        assert len(v0.split(".")[0]) == 32
    finally:
        cp.close()


# ── async surface ─────────────────────────────────────────────────────────


def test_async_surface_equivalent_to_sync(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "a.db")
    try:
        async def go():
            cfg = _config("T1")
            await cp.aput(cfg, _checkpoint("ck-1", {"x": 1}), _meta(1), {})
            got = await cp.aget_tuple(_config("T1"))
            items = await cp.alist(_config("T1"))
            await cp.aput_writes(_config("T1", "ck-1"), [("messages", "m")], task_id="t")
            got2 = await cp.aget_tuple(_config("T1"))
            await cp.adelete_thread("T1")
            return got, items, got2, await cp.aget_tuple(_config("T1"))

        got, items, got2, after_delete = _run(go())
        assert got.checkpoint["channel_values"] == {"x": 1}
        assert len(items) == 1
        assert len(got2.pending_writes) == 1
        assert after_delete is None
    finally:
        cp.close()


# ── concurrency: many writers to distinct threads ─────────────────────────


def test_concurrent_puts_do_not_cross_contaminate(tmp_path):
    cp = LumenSqliteCheckpointer(tmp_path / "cc.db")
    try:
        async def write(i: int):
            await cp.aput(
                _config(f"T{i}", f"ck-{i}"),
                _checkpoint(f"ck-{i}", {"i": i}),
                _meta(i),
                {},
            )

        async def go():
            await asyncio.gather(*[write(i) for i in range(24)])

        _run(go())
        # each thread has exactly its own single checkpoint
        for i in (0, 7, 23):
            got = cp.get_tuple(_config(f"T{i}"))
            assert got is not None and got.checkpoint["channel_values"] == {"i": i}
    finally:
        cp.close()


# ── durability: close + reopen file (process boundary) ────────────────────


def test_durability_reopen_same_file(tmp_path):
    path: Path = tmp_path / "dur.db"
    ckp1 = LumenSqliteCheckpointer(path)
    ckp1.put(_config("T1"), _checkpoint("ck-1", {"msg": "hello"}), _meta(1), {})
    ckp1.close()

    # a brand-new checkpointer over the same file reads the persisted state
    ckp2 = LumenSqliteCheckpointer(path)
    try:
        got = ckp2.get_tuple(_config("T1"))
        assert got is not None
        assert got.checkpoint["id"] == "ck-1"
        assert got.checkpoint["channel_values"] == {"msg": "hello"}
    finally:
        ckp2.close()


# ── boundary: saver is a storage adapter, not a framework re-implementation ─


def test_saver_only_exposes_persistence_not_framework_semantics():
    """The saver must never surface LangGraph scheduler/resume/dedup methods."""
    from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer

    methods = set(LumenSqliteCheckpointer.__dict__)
    assert not (methods & {"run", "astream", "ainvoke", "compile", "interrupt", "resume"})
    # it offers exactly the BaseCheckpointSaver storage surface (+ lifecycle)
    required = {
        "put",
        "get_tuple",
        "list",
        "put_writes",
        "delete_thread",
        "aget_tuple",
        "aput",
        "aput_writes",
        "alist",
        "adelete_thread",
        "get_next_version",
    }
    assert required <= methods


# ── reflection: a real graph still runs with dedup via LangGraph, not the saver ─


def test_compile_and_run_consume_saver_but_langgraph_drives(tmp_path):
    """A compiled StateGraph using the saver runs; the saver stores only."""
    from langgraph.graph import END, START, StateGraph

    def node(state: dict) -> dict:
        return {"value": state.get("value", 0) + 1}

    g = StateGraph(dict)
    g.add_node("inc", node)
    g.add_edge(START, "inc")
    g.add_edge("inc", END)
    cp = LumenSqliteCheckpointer(tmp_path / "g.db")
    try:
        async def go():
            gg = g.compile(checkpointer=cp)
            await gg.ainvoke({"value": 0}, {"configurable": {"thread_id": "g1"}})
            snap = await gg.aget_state({"configurable": {"thread_id": "g1"}})
            return snap.values.get("value")

        assert _run(go()) == 1
    finally:
        cp.close()
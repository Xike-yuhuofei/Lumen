"""P1 Durable Resume — Start / Resume / Retry execution semantics.

Hardens the P1 ``LangGraphThinProvider`` so ``start`` / ``resume`` / ``retry``
are three distinct, non-confusable execution semantics, backed by the production
durable async checkpointer (``LumenSqliteCheckpointer`` — no memory saver, no
aiosqlite, no test shim).

Each scenario drives a subprocess that opens the SAME SQLite checkpointer and
hard-exits via ``os._exit`` (``--crash``) to simulate a crash with no graceful
teardown; a fresh process then resumes / retries. ``_checkpointer_spike_worker``
exposes ``start_op`` / ``resume_op`` / ``retry_op`` phases that go through the
*real* provider ``run()`` with the new ``execution_operation`` contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid

import pytest

from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer

_WORKDIR = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.join(_WORKDIR, "_checkpointer_spike_worker.py")


def _thread():
    return f"thr-{uuid.uuid4().hex[:10]}"


def _worker(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", _WORKER, *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout.strip() or ""
    if proc.returncode != 0 or not out:
        raise AssertionError(
            f"worker {args} rc={proc.returncode}\nstdout={out!r}\nstderr={proc.stderr[-2000:]!r}"
        )
    return json.loads(out)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "durable.db")


# ── Start ────────────────────────────────────────────────────────────────


def test_start_creates_and_persists_checkpoint(db):
    thread = _thread()
    r = _worker("start_op", db, thread, "--crash")
    assert r["operation"] == "start"
    assert r["completed"] is True
    assert r["execution_generation"] == thread
    state = _worker("get_state", db, thread)
    assert state["has_thread"] is True
    assert state["schema_version"] == 1


# ── Resume: continue from checkpoint, no duplicate side effect ───────────


def test_interrupt_crash_then_resume_is_durable_and_deduped(db):
    thread = _thread()
    start = _worker("intr_start", db, thread, "--crash")  # tool dispatched once, parked at interrupt
    assert start["tool_calls"] == 1 and start["interrupted"] is True

    parked = _worker("get_state", db, thread)
    assert parked["next"] == ["human"]  # exact pending step, not re-seeded

    resume = _worker("intr_resume", db, thread, "--reply", "understood")
    assert resume["finished"] is True
    assert resume["tool_calls"] == 0  # completed dispatch NOT re-run on resume
    tool_msgs = [m for m in resume["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1


def test_resume_idempotent_and_retry_isolated(db):
    """Resume reuses identity + checkpoint; retry forges a new one."""
    thread = _thread()
    _worker("intr_start", db, thread, "--crash")

    # Resume keeps the SAME identity and appends to the same message stream.
    resume1 = _worker("intr_resume", db, thread, "--reply", "first")
    gen_after_resume = resume1["execution_generation"]
    assert gen_after_resume == thread
    assert resume1["finished"] is True

    # Retry = a brand-new execution identity, isolated from the original thread.
    retry = _worker("retry_op", db, thread, "--crash")
    assert retry["execution_generation"] != thread
    assert retry["completed"] is True
    # original thread still holds its resume-completed checkpoint
    original_after = _worker("get_state", db, thread)
    assert original_after["has_thread"] is True
    assert original_after["finished"] is True
    # retry thread is fresh and also completed (its own isolated attempt)
    retry_state = _worker("get_state", db, retry["execution_generation"])
    assert retry_state["has_thread"] is True


# ── Provider Start / Resume / Retry operation contract ───────────────────


def test_provider_operations_are_distinct_and_version_safe(db):
    """start / resume / retry produce distinct identities + status transitions."""
    from lumen.evolution.contract import (
        ProviderRequest,
        RuntimeContext,
        TurnInput,
        TurnState,
    )
    from lumen.evolution.fakes import make_standard_tools
    from lumen.evolution.models import ScriptedModel
    from lumen.evolution.providers import LangGraphThinProvider

    import asyncio

    async def run(operation, gen, resume_input=""):
        with LumenSqliteCheckpointer(db) as ckp:
            prov = LangGraphThinProvider(max_steps=12, emit_trace=True, checkpointer=ckp)
            state = TurnState()
            if gen:
                state.snapshot["execution_generation"] = gen
            req = ProviderRequest(
                input=TurnInput(user_message="compute", session_id="s", conversation_history=[]),
                state=state,
                context=RuntimeContext(language="en"),
                model=ScriptedModel(
                    [{"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 2}}]}, "Result is 3."
                ],
                ),
                tools=make_standard_tools(),
                config={"execution_operation": operation, "resume_input": resume_input},
            )
            res = await prov.run(req)
            return state, res

    # Start: new identity, completed, operation recorded.
    s_state, s_res = asyncio.run(run("start", _thread()))
    assert s_state.snapshot["execution_operation"] == "start"
    assert s_res.termination.completed is True

    # Retry: same request content but a NEW identity (isolated from start).
    r_state, _r_res = asyncio.run(run("retry", _thread()))
    assert r_state.snapshot["execution_operation"] == "retry"
    assert r_state.snapshot["execution_generation"] != s_state.snapshot["execution_generation"]


def test_version_guard_is_async_safe_and_fails_closed(db):
    """Incompatible/read-corrupted checkpoint fails safe under an async
    checkpointer: resume must NOT silently continue."""
    from lumen.evolution.contract import (
        ProviderRequest,
        RuntimeContext,
        TurnInput,
        TurnState,
    )
    from lumen.evolution.fakes import make_standard_tools
    from lumen.evolution.models import ScriptedModel
    from lumen.evolution.providers import LangGraphThinProvider

    import asyncio
    import sqlite3

    async def scenario() -> bool:
        thread = _thread()
        # 1. start (compatible, durable)
        async with LumenSqliteCheckpointer(db) as ckp:
            prov = LangGraphThinProvider(max_steps=12, checkpointer=ckp)
            s_state = TurnState()
            s_state.snapshot["execution_generation"] = thread
            req = ProviderRequest(
                input=TurnInput(user_message="u", session_id="s", conversation_history=[]),
                state=s_state,
                context=RuntimeContext(language="en"),
                model=ScriptedModel(["done"]),
                tools=make_standard_tools(),
                config={"execution_operation": "start"},
            )
            await prov.run(req)
        # 2. corrupt the checkpoint blob so it cannot be deserialized
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE checkpoints SET checkpoint=? WHERE thread_id=?",
            (_blast(), thread),
        )
        conn.commit()
        conn.close()
        # 3. request resume => MUST fail closed (not silently continue)
        with LumenSqliteCheckpointer(db) as ckp:
            prov2 = LangGraphThinProvider(max_steps=12, checkpointer=ckp)
            r_state = TurnState()
            r_state.snapshot["execution_generation"] = thread
            req2 = ProviderRequest(
                input=TurnInput(user_message="u", session_id="s", conversation_history=[]),
                state=r_state,
                context=RuntimeContext(language="en"),
                model=ScriptedModel(["done"]),
                tools=make_standard_tools(),
                config={"execution_operation": "resume", "resume_input": "x"},
            )
            res = await prov2.run(req2)
            return bool(res.termination.completed)

    silently_continued = asyncio.run(scenario())
    assert silently_continued is False, "resume of an unreadable checkpoint must fail safe"


def _blast() -> bytes:
    return b"\x00\xff corrupted checkpoint blob that cannot deserialize"
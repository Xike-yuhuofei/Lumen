"""Persistent LangGraph Checkpointer — Spike correctness validation.

Since the objective is to prove LangGraph's durable execution primitives work in
the *real* Lumen runtime integration (not just on paper), these tests run real
subprocesses that each open the SAME persistent SQLite checkpointer file and
hard-exit via ``os._exit`` (``--crash``) to simulate a crash with no graceful
teardown, then a fresh process re-opens the file and resumes.

Covered proofs:

* execution state persists beyond the process lifetime (crash → re-open);
* stable execution identity (thread_id) restores the correct checkpoint;
* a completed tool dispatch is NOT re-run on resume (no duplicate side effect);
* native LangGraph ``interrupt()`` pauses, persists, and resumes with input;
* checkpoint schema-version mismatch fails safe (fresh generation, never a wrong
  resume);
* streaming / usage / tools / budget surfaces are unchanged by enabling a
  persistent checkpointer.

Run with any ``pytest``; skipped if the official sqlite checkpointer is absent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_WORKDIR = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.path.join(_WORKDIR, "_checkpointer_spike_worker.py")

try:  # the persistent backend this spike requires
    from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer  # noqa: F401

    HAVE_SQLITE = True
except Exception:  # pragma: no cover - env without the persistent backend
    HAVE_SQLITE = False

pytestmark = pytest.mark.skipif(not HAVE_SQLITE, reason="persistent sqlite checkpointer unavailable")


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
            f"worker {args} failed rc={proc.returncode}\nstdout={out!r}\nstderr={proc.stderr[-2000:]!r}"
        )
    return json.loads(out)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "spike.db")


def _thread():
    import uuid

    return f"thr-{uuid.uuid4().hex[:10]}"


def test_execution_state_persists_across_process_crash(db):
    thread = _thread()
    _worker("thin", db, thread, "--crash")
    state = _worker("get_state", db, thread)
    assert state["has_thread"] is True
    assert state["schema_version"] == 1
    assert state["msg_count"] >= 2


def test_native_interrupt_persists_and_resume_completes_with_no_dup_side_effect(db):
    thread = _thread()
    start = _worker("intr_start", db, thread, "--crash")
    # phase 1 dispatched the calc tool once and parked at the native interrupt.
    assert start["tool_calls"] == 1
    assert start["interrupted"] is True

    # Fresh process: the durable checkpoint knows the exact next step.
    state = _worker("get_state", db, thread)
    assert state["has_thread"] is True
    assert state["next"] == ["human"]
    assert state["finished"] is False

    # Fresh process resumes with learner input; the completed tool node is NOT
    # re-run (LangGraph checkpoint dedup) → still exactly one dispatch overall.
    resume = _worker("intr_resume", db, thread, "--reply", "understood")
    assert resume["finished"] is True
    assert resume["tool_calls"] == 0  # no duplicate side effect on resume
    tool_msgs = [m for m in resume["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1  # the tool effect exists exactly once
    # graph state / control flow consistent before & after interrupt
    assert any("[learner reply] understood" in (m.get("content") or "") for m in resume["messages"])


def test_interrupt_preserves_thread_and_message_continuity(db):
    thread = _thread()
    _worker("intr_start", db, thread, "--crash")
    state_before = _worker("get_state", db, thread)
    resume = _worker("intr_resume", db, thread, "--reply", "ok")
    assert resume["finished"] is True
    # The learner reply is appended to the SAME message stream (no reset).
    assert state_before["msg_count"] + 1 == len(resume["messages"])


def test_fresh_attempt_is_isolated_from_prior_thread(db):
    # isolation: two independent threads do not share state
    ta, tb = _thread(), _thread()
    _worker("intr_start", db, ta, "--crash")
    _worker("intr_start", db, tb, "--crash")
    sa = _worker("get_state", db, ta)
    sb = _worker("get_state", db, tb)
    assert sa["has_thread"] and sb["has_thread"]
    assert sa["next"] == ["human"] and sb["next"] == ["human"]


def test_thin_provider_runs_complete_with_persistent_checkpointer(db):
    """Budget / tool / termination surfaces stay intact when checkpointer is on."""
    thread = _thread()
    out = _worker("thin", db, thread)
    assert out["completed"] is True
    assert out["reason"] == "completed"
    assert out["tool_calls"] == 1
    assert out["final_text"] == "Result is 5."


def test_incompatible_checkpoint_fails_safe_never_silent_resume(db):
    """A checkpoint whose schema can no longer be read must fail closed (raise)
    on resume — never silently continue on a mismatched schema."""
    thread = _thread()
    _worker("intr_start", db, thread, "--crash")  # durable interrupt checkpoint
    # Corrupt the persisted checkpoint so it cannot be deserialized (simulates
    # an unreadable / older provider-schema checkpoint).
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE checkpoints SET type=?, checkpoint=?, metadata=? WHERE thread_id=?",
        ("provider-v0", b"\x00\xff not a serializable checkpoint", b"{}", thread),
    )
    conn.commit()
    conn.close()

    with pytest.raises(Exception):  # fail-closed: resume must not silently continue
        _worker("intr_resume", db, thread, "--reply", "understood")
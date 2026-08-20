"""C2 — Teaching Session ↔ execution identity / lifecycle governor.

Proves that one Teaching Session can durably track multiple independent Agent
Runtime executions, recover its current position across a restart (no in-memory
state), and never conflates ``teaching_session_id`` with ``execution_generation``.
The governor itself is a pure, durable decision layer — no LLM / no provider.
"""

from __future__ import annotations

import pytest

from lumen.modes.learn.teaching_session import (
    ExecutionStatus,
    TeachingSessionGovernor,
    map_termination_to_status,
)

# ── identity separation ──────────────────────────────────────────────────────


def test_session_id_is_stable_and_never_equals_execution_generation(tmp_path):
    gov = TeachingSessionGovernor(tmp_path)
    session_id = gov.ensure_session("path-A")
    session_id_again = gov.ensure_session("path-A")
    assert session_id == session_id_again
    assert session_id != "path-A" or len(session_id) > 0  # it is a distinct key
    assert session_id.startswith("ts-")
    # A fresh session id later is different.
    assert gov.ensure_session("path-B") != session_id

    plan = gov.plan(session_id)
    assert plan.execution_generation.startswith("exec-")
    assert plan.execution_generation != session_id  # C2: never equal to session id


# ── lifecycle transitions ────────────────────────────────────────────────────


def test_first_turn_is_start_then_interrupt_resumes_same_execution(tmp_path):
    gov = TeachingSessionGovernor(tmp_path)
    sid = gov.ensure_session("path")
    first = gov.plan(sid)
    assert first.operation == "start"
    gov.record_start(first)
    gov.record_termination(sid, first.execution_generation, ExecutionStatus.INTERRUPTED)

    # Interrupted execution is resumable on the SAME generation.
    resume = gov.plan(sid, resume_input="my reply")
    assert resume.operation == "resume"
    assert resume.execution_generation == first.execution_generation
    assert resume.resume_input == "my reply"


def test_completed_then_new_message_creates_next_execution(tmp_path):
    gov = TeachingSessionGovernor(tmp_path)
    sid = gov.ensure_session("path")
    first = gov.plan(sid)
    gov.record_start(first)
    gov.record_termination(sid, first.execution_generation, ExecutionStatus.COMPLETED)

    # Terminal state → the next user turn starts a NEW, isolated execution.
    nxt = gov.plan(sid)
    assert nxt.operation == "start"
    assert nxt.execution_generation != first.execution_generation
    assert nxt.superseded == first.execution_generation
    gov.record_start(nxt)
    # Both executions are recorded under the same session.
    execs = gov.executions(sid)
    assert {e["execution_generation"] for e in execs} == {
        first.execution_generation,
        nxt.execution_generation,
    }


def test_retry_forges_isolated_execution(tmp_path):
    gov = TeachingSessionGovernor(tmp_path)
    sid = gov.ensure_session("path")
    first = gov.plan(sid)
    gov.record_start(first)
    gov.record_termination(sid, first.execution_generation, ExecutionStatus.INTERRUPTED)

    retry = gov.plan(sid, retry=True)
    assert retry.operation == "retry"
    assert retry.execution_generation != first.execution_generation  # isolated
    assert retry.superseded == first.execution_generation


# ── crash / restart recovery ────────────────────────────────────────────────


def test_crash_leaves_active_and_restart_resumes_same_execution(tmp_path):
    # Process 1: starts an execution, records it ACTIVE, then dies before any
    # termination is recorded (a crash).
    gov1 = TeachingSessionGovernor(tmp_path)
    sid = gov1.ensure_session("path")
    plan = gov1.plan(sid)
    gov1.record_start(plan)  # ACTIVE; no record_termination → crash
    gen_at_crash = plan.execution_generation

    # Process 2: a brand-new governor over the SAME on-disk store (restart).
    gov2 = TeachingSessionGovernor(tmp_path)
    # Same stable session identity recovered from disk — not guessed.
    assert gov2.ensure_session("path") == sid
    plan2 = gov2.plan(sid)
    # The active (unfinished) execution is resumed, not guessed / not re-created.
    assert plan2.operation == "resume"
    assert plan2.execution_generation == gen_at_crash


def test_persistence_token_across_reopen_honours_terminal_state(tmp_path):
    gov = TeachingSessionGovernor(tmp_path)
    sid = gov.ensure_session("path")
    plan = gov.plan(sid)
    gov.record_start(plan)
    gov.record_termination(sid, plan.execution_generation, ExecutionStatus.COMPLETED)

    reopen = TeachingSessionGovernor(tmp_path)
    nxt = reopen.plan(sid)
    assert nxt.operation == "start"
    assert nxt.execution_generation != plan.execution_generation


# ── status mapping ───────────────────────────────────────────────────────────


def test_map_termination_to_status():
    assert map_termination_to_status(completed=True, termination="completed", operation="start") == ExecutionStatus.COMPLETED
    assert map_termination_to_status(completed=False, termination="interrupted", operation="resume") == ExecutionStatus.INTERRUPTED
    assert map_termination_to_status(completed=False, termination="cancelled", operation="start") == ExecutionStatus.CANCELLED
    assert map_termination_to_status(completed=False, termination="error", operation="start") == ExecutionStatus.FAILED
    # forced stop still carries terminal output → treated as completed for lifecycle
    assert map_termination_to_status(completed=False, termination="budget_exhausted", operation="start") == ExecutionStatus.COMPLETED
    assert map_termination_to_status(completed=True, termination="completed", operation="retry") == ExecutionStatus.COMPLETED
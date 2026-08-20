"""Teaching Session Graph Candidate — Fault / Concurrency / Replay Hard Gate.

Production-correctness gate for the minimal Teaching Session Graph Candidate.
The invariant under test is the whole point of the commit foundation:

    at-least-once execution + effectively-once authoritative learner effect

The gate is split into three batteries:

* **Fault**  — crash before/at/after a DomainCommit must never leave a
  half-applied learner state, and every resume must collapse the crashing
  action to a single effect.  The graph-node checkpoint is advisory-only, so a
  corrupt / version-incompatible checkpoint row must fail-safe (never be
  honoured) and never mis-resume.
* **Concurrency** — two Teaching Sessions over the same learner must not
  silently lose an update; conflicts resolve through the existing CAS +
  reconciliation (stale derived state rejected, evidence retained, stale
  PolicyDecision marked), and one ``action_id`` races to exactly one effect.
* **Replay**     — Decision Replay (reuse an immutable PolicyDecision from the
  ledger without re-running the policy), Control-flow Replay (the recorded
  decision drives the identical graph path), and Effect Replay (a re-issued
  action collapses to a REPLAYED receipt, no duplicate side effect).  Replay
  is read-only and never pollutes the current learner authority.

It reuses the real Candidate graph, Domain Commit Foundation, Teaching
Session lifecycle identities and checkpoint — no stubbed orchestrator.  The
only fakes are the learner content agent loop and a recorded/scripted
deterministic decision where the goal explicitly calls for recorded output.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.application.teaching_service import TeachingService
from lumen.modes.learn.assessment.grading import grade_answer
from lumen.modes.learn.commit.commit_service import DomainCommitService
from lumen.modes.learn.commit.contract import (
    CommitStatus,
    DomainCommitRequest,
    Evidence,
)
from lumen.modes.learn.commit.identity import commit_id, evidence_id
from lumen.modes.learn.commit.outbox import OutboxDispatcher
from lumen.modes.learn.commit.repository import LearnerDomainRepository
from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint
from lumen.modes.learn.graph.contract import PolicyDecision, TeachingNode
from lumen.modes.learn.graph.domain_service import TeachingGraphDomain
from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler
from lumen.runtime.context import UnifiedContext
from lumen.runtime.session.sqlite_store import SQLiteSessionStore

# ── shared fakes / helpers ────────────────────────────────────────────────


class _FakeStream:
    def __init__(self):
        self.events = []

    async def emit(self, event, *, source=None, stage=None, metadata=None):
        self.events.append(("emit", event))

    async def content(self, text, *, source=None, stage=None):
        self.events.append(("content", text))


class _FakeAgentLoop:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self, *, context=None, stream=None, language="en", **config):
        self.runs += 1
        if context is not None:
            context.metadata["exec_completed"] = True


def _make_progress(path_id, *, kp_desc="yes", kp_type=KnowledgeType.CONCEPT):
    progress = LearningProgress(book_id=path_id)
    kp = KnowledgePoint(
        id=f"{path_id}_kp0",
        name="Photosynthesis",
        type=kp_type,
        module_id=f"{path_id}_m0",
        description=kp_desc,
    )
    module = LearningModule(id=f"{path_id}_m0", name="Biology", order=0, knowledge_points=[kp])
    progress.modules = [module]
    progress.knowledge_types[kp.id] = kp.type
    return progress, kp


def _pending(kp, *, pqid, decision_id, expected="yes"):
    return PendingQuestion(
        question_id=pqid,
        knowledge_point_id=kp.id,
        module_id=kp.module_id,
        prompt="Q",
        question_type="short",
        expected_answer=expected,
        decision_id=decision_id,
        action_id=f"{decision_id}:pose",
    )


def _graph(store, *, checkpoint=None):
    return TeachingSessionGraph(
        store=store,
        domain=TeachingGraphDomain(store),
        teaching_service=TeachingService(learning_store=store),
        checkpoint=checkpoint,
    )


def _run(
    graph,
    *,
    path_id,
    stream,
    agent,
    resume_input=None,
    gen="exec-1",
    op="start",
    ts="ts-test",
):
    ctx = UnifiedContext(session_id="sess", user_message=resume_input or "hi", language="en")
    ctx.metadata["mastery_mode"] = True
    ctx.metadata["turn_id"] = "turn-1"
    import asyncio

    return asyncio.run(
        graph.run_turn(
            path_id=path_id,
            teaching_session_id=ts,
            execution_generation=gen,
            execution_operation=op,
            resume_input=resume_input,
            context=ctx,
            stream=stream,
            agent_loop=agent,
            deps={},
        )
    )


def _grade_request(
    book,
    kp,
    *,
    action_id,
    decision_id,
    question_id,
    expected,
    user_ans,
    version,
    correct=None,
):
    """Build a grade DomainCommitRequest shaped exactly like the graph's
    ``TeachingGraphDomain.commit_grade`` (evidence + decision lineage)."""
    is_correct = grade_answer(user_ans, expected, "short") if correct is None else correct
    lp = LearningProgress(book_id=book)
    mod = LearningModule(id=kp.module_id, name="M", order=0, knowledge_points=[kp])
    lp.modules = [mod]
    lp.knowledge_types[kp.id] = kp.type
    ev = Evidence(
        target_type="knowledge_point",
        target_id=kp.id,
        evidence_type="quiz_answer",
        outcome=is_correct,
        outcome_json={
            "is_correct": is_correct,
            "question_id": question_id,
            "module_id": kp.module_id,
            "question_kind": "recall",
            "error_type": None if is_correct else "application_error",
            "self_attribution": "",
            "misconception_node_id": "",
        },
        raw_response_json={"user_answer": user_ans},
        evaluator_kind="deterministic",
        evaluator_version="graph-candidate:v1",
        decision_id=decision_id,
        observed_at_ms=1_000,
    )
    return DomainCommitRequest(
        learner_id=book,
        action_id=action_id,
        expected_learner_version=version,
        proposed_state=lp.model_dump(mode="json"),
        evidence=[ev],
        decision={
            "decision_id": decision_id,
            "policy_version": "teaching-engine:v1",
            "action": "assess",
        },
        decision_id=decision_id,
    )


def _seed_open_question(store, path_id, kp, *, decision_id, expected="yes"):
    progress, _ = _make_progress(path_id, kp_desc="light into chemical energy")
    progress.pending_question = _pending(kp, pqid="q", decision_id=decision_id, expected=expected)
    store.save(progress)


def _assert_no_dup(store, path_id, *, expected_actions):
    with store._repo.tx():
        actions = [row["action_id"] for row in store._repo.get_evidence_ledger(path_id)]
    assert actions == expected_actions


# ═══════════════════════════════════════════════════════════════════════════
# FAULT  — crash / resume / idempotency / fail-safe
# ═══════════════════════════════════════════════════════════════════════════


def test_fault_00_crash_mid_commit_no_half_applied_state(tmp_path, monkeypatch):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("fa", kp_desc="yes")
    _p.pending_question = _pending(kp, pqid="q", decision_id="dec-fa")
    store.save(_p)
    domain = TeachingGraphDomain(store)
    sched = SpacedRepetitionScheduler()

    def _boom(*_a, **_k):
        raise RuntimeError("simulated kill after evidence insert")

    monkeypatch.setattr(store._repo, "insert_learner_event", _boom)
    with pytest.raises(RuntimeError):
        domain.commit_grade(
            _p,
            pending=_p.pending_question,
            user_answer="yes",
            choice_options={},
            expected_answer="yes",
            answer_for_grading="yes",
            misconception_node_id="",
            scheduler=sched,
        )
    # No half-applied learner state: nothing was committed.
    assert store._repo.integrity_ok()
    with store._repo.tx():
        ledger = store._repo.get_evidence_ledger("fa")
        dec_row = store._repo._conn.execute(
            "SELECT 1 FROM policy_decisions WHERE decision_id='dec-fa'"
        ).fetchone()
    assert len(ledger) == 0
    assert store._repo.get_commit("fa", "dec-fa:graded") is None
    assert store.current_version("fa") == 1  # only the seed commit
    assert dec_row is None  # the decision insert also rolled back

    monkeypatch.undo()
    # A clean resume commits exactly once — no half state, no duplicate.
    fresh = store.load("fa")
    assert fresh is not None and fresh.pending_question is not None
    ok = domain.commit_grade(
        fresh,
        pending=fresh.pending_question,
        user_answer="yes",
        choice_options={},
        expected_answer="yes",
        answer_for_grading="yes",
        misconception_node_id="",
        scheduler=sched,
    )
    assert ok is True
    _assert_no_dup(store, "fa", expected_actions=["dec-fa:graded"])


def test_fault_01_commit_done_checkpoint_not_advanced_no_dup(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("fb", kp_desc="yes", kp_type=KnowledgeType.MEMORY)
    _p.pending_question = _pending(kp, pqid="q", decision_id="dec-cb")
    store.save(_p)
    graph = _graph(store, checkpoint=TeachingGraphCheckpoint(tmp_path / "ckp"))
    out = _run(graph, path_id="fb", stream=_FakeStream(), agent=_FakeAgentLoop(), resume_input="yes")
    assert out.graded is True and out.committed is True
    # Crash AFTER the DomainCommit succeeded but BEFORE the graph's checkpoint
    # advanced — re-running the SAME path must NEVER re-commit the already
    # committed grade (the graph re-derives from the cleared snapshot).
    _run(graph, path_id="fb", stream=_FakeStream(), agent=_FakeAgentLoop(), resume_input="yes")
    with store._repo.tx():
        acts = [row["action_id"] for row in store._repo.get_evidence_ledger("fb")]
    assert acts.count("dec-cb:graded") == 1  # exactly one effect for that action
    assert len(store.load("fb").quiz_attempts) == 2  # seeded grade + its fresh pose
    assert sum(1 for a in store.load("fb").quiz_attempts if a.question_id == "q") == 1


def test_fault_02_corrupted_checkpoint_is_fail_safe(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("fc", kp_desc="yes", kp_type=KnowledgeType.MEMORY)
    _p.pending_question = _pending(kp, pqid="q", decision_id="dec-fc")
    store.save(_p)
    v = store.current_version("fc")
    ckp = TeachingGraphCheckpoint(tmp_path / "ckp")
    # Inject a corrupt, version-incompatible row under the EXACT key the graph
    # will use, pretending the learner is at 999 and already TERMINATED. The
    # graph must never honour advisory state.
    ckp.record(
        teaching_session_id="ts-test",
        execution_generation="exec-1",
        last_node="terminate",
        learner_version=999,
        decision_id="bogus",
    )
    graph = _graph(store, checkpoint=ckp)
    out = _run(graph, path_id="fc", stream=_FakeStream(), agent=_FakeAgentLoop(), resume_input="yes")
    # Re-derived from the TRUE snapshot, not from the corrupt 'terminate' / 999.
    assert out.graded is True and out.committed is True
    assert store.current_version("fc") != 999  # real CAS version, never the carted 999
    assert store.current_version("fc") >= v  # advanced by real commits, not the bogus row
    pos = ckp.position("ts-test", "exec-1")
    assert pos is not None
    assert pos["learner_version"] != 999  # the graph overwrote the corrupt row
    assert pos["last_node"] != "terminate"


def test_fault_03_crash_resume_across_processes_single_effect(tmp_path):
    root = tmp_path
    storeA = LearningStore(root)
    kp = _make_progress("fd", kp_desc="light into chemical energy")[1]
    _seed_open_question(storeA, "fd", kp, decision_id="dec-xp", expected="light")
    graphA = _graph(storeA, checkpoint=TeachingGraphCheckpoint(root / "ckp"))
    # Process A presents/parks the open question but crashes before grading.
    _run(graphA, path_id="fd", stream=_FakeStream(), agent=_FakeAgentLoop(), gen="exec-1")
    # Process B = brand-new instances (fresh connections) on the SAME files.
    storeB = LearningStore(root)
    ckpB = TeachingGraphCheckpoint(root / "ckp")
    graphB = _graph(storeB, checkpoint=ckpB)
    out = _run(
        graphB,
        path_id="fd",
        stream=_FakeStream(),
        agent=_FakeAgentLoop(),
        resume_input="light",
        gen="exec-2",
    )
    assert out.graded is True
    _assert_no_dup(storeB, "fd", expected_actions=["dec-xp:graded"])
    # Checkpoint rows are isolated per (teaching_session, execution_generation).
    assert ckpB.position("ts-test", "exec-1") is not None
    assert ckpB.position("ts-test", "exec-2") is not None
    assert ckpB.position("ts-test", "exec-1")["last_node"] != ckpB.position(
        "ts-test", "exec-2"
    )["last_node"] or ckpB.position("ts-test", "exec-1")["learner_version"] != ckpB.position(
        "ts-test", "exec-2"
    )["learner_version"]


def test_fault_04_agent_runtime_crash_is_contained_no_effect(tmp_path):
    store = LearningStore(tmp_path)
    _p, _ = _make_progress("fe", kp_desc="photosynthesis converts light to chemical energy")
    store.save(_p)
    graph = _graph(store)
    v0 = store.current_version("fe")

    class _Boom:
        async def run(self, **kw):
            raise RuntimeError("agent runtime crashed")

    out = _run(graph, path_id="fe", stream=_FakeStream(), agent=_Boom())
    # A broken content pass is contained: the graph returns a controlled
    # continuation and writes NO learner effect.
    assert out.node == TeachingNode.CONTINUE
    assert out.committed is None
    with store._repo.tx():
        n = len(store._repo.get_evidence_ledger("fe"))
    assert n == 0
    assert store.current_version("fe") == v0


def test_fault_05_checkpoint_rows_isolated_by_generation(tmp_path):
    ckp = TeachingGraphCheckpoint(tmp_path / "ckp")
    ckp.record(teaching_session_id="ts", execution_generation="g1", last_node="decide",
               learner_version=1, decision_id="d1")
    ckp.record(teaching_session_id="ts", execution_generation="g2", last_node="act",
               learner_version=2, decision_id="d2")
    assert ckp.position("ts", "g1")["last_node"] == "decide"
    assert ckp.position("ts", "g2")["last_node"] == "act"
    # Overwriting one generation never bleeds into another.
    ckp.record(teaching_session_id="ts", execution_generation="g1", last_node="act",
               learner_version=3, decision_id="d3")
    assert ckp.position("ts", "g1")["decision_id"] == "d3"
    assert ckp.position("ts", "g2")["last_node"] == "act"
    assert ckp.position("ts", "g2")["decision_id"] == "d2"
    # Different teaching_session_id is a separate namespace too.
    ckp.record(teaching_session_id="ts2", execution_generation="g1", last_node="terminate")
    assert ckp.position("ts", "g1") is not None
    assert ckp.position("ts2", "g1")["last_node"] == "terminate"


def test_fault_06_outbox_side_effect_recovers_without_duplicate(tmp_path):
    """Graph checkpoint/domain already advanced but the external side effect
    (question-bank projection) is not yet done: the transactional outbox lets the
    system detect and recover it — and a lost delivery-mark replays idempotently.
    """
    import sqlite3

    store = LearningStore(tmp_path)
    _p, kp = _make_progress("fg", kp_desc="yes")
    _p.pending_question = _pending(kp, pqid="q", decision_id="dec-og")
    store.save(_p)
    domain = TeachingGraphDomain(store)
    chat = SQLiteSessionStore(db_path=tmp_path / "chat.db")
    session = asyncio.run(chat.create_session(title="s"))
    payload = {
        "session_id": session["id"],
        "turn_id": "t1",
        "question_id": "q1",
        "question": "Q?",
        "is_correct": True,
        "user_answer": "yes",
    }
    # The authoritative grade commit atomically carries the external projection.
    domain.commit_grade(
        store.load("fg"),
        pending=store.load("fg").pending_question,
        user_answer="yes",
        choice_options={},
        expected_answer="yes",
        answer_for_grading="yes",
        misconception_node_id="",
        scheduler=SpacedRepetitionScheduler(),
        question_bank=payload,
    )
    # DomainCommit / checkpoint advanced, but the external side effect is pending.
    with store._repo.tx():
        pending_outbox = store._repo.pending_outbox()
    assert len(pending_outbox) == 1
    assert pending_outbox[0]["delivered_at_ms"] is None
    # The system detects & recovers it: dispatch completes the projection.
    disp = OutboxDispatcher(repository=store._repo, chat_db_path=tmp_path / "chat.db")
    assert disp.dispatch()["ok"] == 1
    # Simulate a crash BETWEEN the target write and the source delivery-mark:
    # re-dispatch must recover idempotently with exactly one external effect.
    event_id = pending_outbox[0]["event_id"]
    with store._repo.tx():
        store._repo._conn.execute(
            "UPDATE outbox_events SET delivered_at_ms=NULL WHERE event_id=?", (event_id,)
        )
        store._repo._conn.commit()
    assert disp.dispatch()["ok"] == 1
    conn = sqlite3.connect(str(tmp_path / "chat.db"))
    conn.row_factory = sqlite3.Row
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM notebook_entries WHERE question_id='q1'"
        ).fetchone()["c"]
    finally:
        conn.close()
    assert cnt == 1  # no duplicate external side effect on recovery


# ═══════════════════════════════════════════════════════════════════════════
# CONCURRENCY  — CAS / no lost update / stale superseded / effectively-once
# ═══════════════════════════════════════════════════════════════════════════


def test_conc_01_two_sessions_same_version_no_silent_lost_update(tmp_path):
    storeA = LearningStore(tmp_path)
    storeB = LearningStore(tmp_path)  # separate connection == separate Teaching Session
    _p, kp = _make_progress("c1", kp_desc="yes")
    storeA.save(_p)
    v = storeA.current_version("c1")
    svcA = DomainCommitService(storeA._repo)
    svcB = DomainCommitService(storeB._repo)
    # Both sessions captured learner version v, then raced on DIFFERENT pending
    # decisions. No silent lost update / stale overwrite is allowed.
    rA = svcA.commit(
        _grade_request("c1", kp, action_id="decA:graded", decision_id="decA",
                       question_id="qa", expected="yes", user_ans="yes", version=v)
    )
    rB = svcB.commit(
        _grade_request("c1", kp, action_id="decB:graded", decision_id="decB",
                       question_id="qb", expected="no", user_ans="no", version=v)
    )
    assert rA.status == CommitStatus.APPLIED and rA.resulting_version == v + 1
    assert rB.status == CommitStatus.APPLIED_RECONCILED and rB.resulting_version == v + 2
    # BOTH evidences preserved (legal evidence is never lost).
    with storeA._repo.tx():
        ledger = storeA._repo.get_evidence_ledger("c1")
        state = json.loads(storeA._repo.get_aggregate("c1")["state_json"])
    assert len(ledger) == 2
    assert {row["decision_id"] for row in ledger} == {"decA", "decB"}
    # ...and the losing session's stale derived snapshot was NOT accepted.
    assert len(state["quiz_attempts"]) == 2  # canonical projection of both grades
    assert rB.decision_stale is True and rB.requires_redecision is True


def test_conc_02_same_action_id_concurrent_single_effect(tmp_path):
    db = tmp_path / "learner.db"
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("c2", kp_desc="yes")
    store.save(_p)
    v = store.current_version("c2")
    outcomes = []

    def run():
        s = LearningStore(tmp_path)
        svc = DomainCommitService(s._repo)
        try:
            r = svc.commit(
                _grade_request("c2", kp, action_id="decS:graded", decision_id="decS",
                               question_id="qs", expected="yes", user_ans="yes", version=v)
            )
            outcomes.append(r.status)
        except Exception as exc:  # noqa: BLE001
            outcomes.append(str(type(exc).__name__))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    repo = LearnerDomainRepository(db_path=db)
    commits = repo._conn.execute("SELECT * FROM domain_commits").fetchall()
    grade_commits = [c for c in commits if c["action_id"] == "decS:graded"]
    assert len(grade_commits) == 1  # one durable authoritative effect
    with repo.tx():
        ledger = repo.get_evidence_ledger("c2")
    assert len(ledger) == 1
    # No caller duplicated the effect even though many raced on the same action.


def test_conc_03_stale_decision_marked_and_triggers_fresh_redecision(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("c3", kp_desc="yes")
    store.save(_p)
    v = store.current_version("c3")
    svc = DomainCommitService(store._repo)
    svc.commit(
        _grade_request("c3", kp, action_id="decS1:graded", decision_id="decS1",
                       question_id="qs", expected="yes", user_ans="yes", version=v)
    )
    # A second session commits an OLD decision S0 it captured against version v.
    rS0 = svc.commit(
        _grade_request("c3", kp, action_id="decS0:graded", decision_id="decS0",
                       question_id="q0", expected="no", user_ans="no", version=v)
    )
    assert rS0.status == CommitStatus.APPLIED_RECONCILED
    assert rS0.decision_stale is True and rS0.requires_redecision is True
    with store._repo.tx():
        stale_events = store._repo._conn.execute(
            "SELECT kind FROM policy_decision_events WHERE decision_id='decS0' "
            "AND kind='stale'"
        ).fetchall()
    assert len(stale_events) == 1  # stale/superseded expressed as an event
    # The graph's NEXT live decision is a brand-new id, never the stale decS0.
    graph = _graph(store)
    out = _run(graph, path_id="c3", stream=_FakeStream(), agent=_FakeAgentLoop())
    assert out.decision.decision_id.startswith("dec-")
    assert out.decision.decision_id not in ("decS0", "decS1")


def test_conc_05_no_state_bleed_across_learners(tmp_path):
    store = LearningStore(tmp_path)
    pA, kpA = _make_progress("CA", kp_desc="yes")
    pB, kpB = _make_progress("CB", kp_desc="yes")
    store.save(pA)
    store.save(pB)
    svc = DomainCommitService(store._repo)
    svc.commit(
        _grade_request("CA", kpA, action_id="decA:graded", decision_id="decA",
                       question_id="qA", expected="yes", user_ans="yes",
                       version=store.current_version("CA"))
    )
    svc.commit(
        _grade_request("CB", kpB, action_id="decB:graded", decision_id="decB",
                       question_id="qB", expected="yes", user_ans="yes",
                       version=store.current_version("CB"))
    )
    with store._repo.tx():
        evA = store._repo.get_evidence_ledger("CA")
        evB = store._repo.get_evidence_ledger("CB")
        decA = store._repo._conn.execute(
            "SELECT learner_id FROM policy_decisions WHERE decision_id='decA'"
        ).fetchone()
        decB = store._repo._conn.execute(
            "SELECT learner_id FROM policy_decisions WHERE decision_id='decB'"
        ).fetchone()
    assert len(evA) == 1 and len(evB) == 1
    assert all(e["decision_id"] == "decA" for e in evA)
    assert all(e["decision_id"] == "decB" for e in evB)
    assert decA["learner_id"] == "CA" and decB["learner_id"] == "CB"


# ═══════════════════════════════════════════════════════════════════════════
# REPLAY  — Decision / Control-flow / Effect Replay (read-only, isolated)
# ═══════════════════════════════════════════════════════════════════════════


def test_replay_01_decision_replay_reuses_immutable_without_policy(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("r1", kp_desc="yes")
    _p.pending_question = _pending(kp, pqid="q", decision_id="dec-commit")
    store.save(_p)
    domain = TeachingGraphDomain(store)
    graph = _graph(store)
    v0 = store.current_version("r1")
    progress = store.load("r1")
    domain.commit_pose(
        progress,
        progress.pending_question,
        decision_payload={"decision_id": "dec-commit", "policy_version": "teaching-engine:v1", "action": "assess"},
        decision_id="dec-commit",
    )
    vev = store.current_version("r1")
    assert vev == v0 + 1
    # Decision Replay: reconstruct the committed decision WITHOUT re-running policy.
    policy_calls = []
    orig = graph._teaching.decide
    graph._teaching.decide = lambda pid: policy_calls.append(pid) or orig(pid)
    replayed = graph.replay_decision("dec-commit")
    assert policy_calls == []  # the policy was never re-invoked
    assert replayed is not None
    assert replayed.decision_id == "dec-commit"
    assert replayed.action == "assess"
    assert replayed.policy_version == "teaching-engine:v1"
    # Replay is strictly read-only: nothing advances or mutates the authority.
    assert store.current_version("r1") == vev
    assert graph.replay_decision("dec-never-committed") is None
    with store._repo.tx():
        cnt = store._repo._conn.execute(
            "SELECT COUNT(*) c FROM policy_decisions WHERE decision_id='dec-never-committed'"
        ).fetchone()["c"]
    assert cnt == 0


def test_replay_02_control_flow_replay_reproduces_path(tmp_path):
    # Two independent storage roots driven by the SAME recorded decision must
    # walk the identical graph path and produce identical lineage.
    recorded = PolicyDecision(
        decision_id="decN", policy_version="teaching-engine:v1", action="assess",
        focus_node_id="r2_kp0",
    )
    per_storage = {}
    for name in ("a", "b"):
        store = LearningStore(tmp_path / name)
        _p_, kp = _make_progress("r2", kp_desc="light into chemical energy")
        _seed_open_question(store, "r2", kp, decision_id="decR", expected="light")
        graph = _graph(store)
        graph._decide = lambda _path, _prog: recorded  # recorded decision drives the path
        out = _run(graph, path_id="r2", stream=_FakeStream(), agent=_FakeAgentLoop(),
                   resume_input="light", gen=f"exec-{name}")
        assert out.graded is True
        assert out.node == TeachingNode.CONTINUE
        with store._repo.tx():
            acts = [row["action_id"] for row in store._repo.get_evidence_ledger("r2")]
        # The recorded decision routed the graph into the SAME post-grade pose.
        posed = store.load("r2").pending_question
        per_storage[name] = (out.node, acts, posed.decision_id if posed else "")
    # Identical node path, identical effect lineage, identical routing decision.
    assert per_storage["a"] == per_storage["b"]
    assert per_storage["a"][2] == "decN"  # the same recorded decision was used


def test_replay_03_effect_replay_no_duplicate_side_effect(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("r3", kp_desc="yes")
    store.save(_p)
    v = store.current_version("r3")
    svc = DomainCommitService(store._repo)
    req = _grade_request("r3", kp, action_id="decE:graded", decision_id="decE",
                         question_id="q", expected="yes", user_ans="yes", version=v)
    first = svc.commit(req)
    assert first.status == CommitStatus.APPLIED
    with store._repo.tx():
        ev_before = len(store._repo.get_evidence_ledger("r3"))
        evt_before = store._repo._conn.execute(
            "SELECT COUNT(*) c FROM learner_events"
        ).fetchone()["c"]
    # Effect Replay: re-issuing the SAME action+payload collapses to a receipt.
    replay = svc.commit(req)
    assert replay.status == CommitStatus.REPLAYED
    assert replay.replayed is True
    with store._repo.tx():
        ev_after = len(store._repo.get_evidence_ledger("r3"))
        evt_after = store._repo._conn.execute(
            "SELECT COUNT(*) c FROM learner_events"
        ).fetchone()["c"]
    assert ev_after == ev_before == 1  # no duplicate evidence row
    assert evt_after == evt_before  # no duplicate audit event
    assert store.current_version("r3") == first.resulting_version  # no version bump


def test_replay_04_replay_does_not_mutate_facts_or_pollute_authority(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("r4", kp_desc="yes")
    _p.pending_question = _pending(kp, pqid="q", decision_id="decP")
    store.save(_p)
    domain = TeachingGraphDomain(store)
    graph = _graph(store)
    progress = store.load("r4")
    domain.commit_pose(
        progress,
        progress.pending_question,
        decision_payload={"decision_id": "decP", "policy_version": "teaching-engine:v1", "action": "assess"},
        decision_id="decP",
    )
    with store._repo.tx():
        hash_before = store._repo.get_policy_decision_hash("decP")
    version_before = store.current_version("r4")
    # Repeated Decision Replay returns a stable reconstruction and mutates nothing.
    r1 = graph.replay_decision("decP")
    r2 = graph.replay_decision("decP")
    assert r1.to_payload() == r2.to_payload()
    with store._repo.tx():
        hash_after = store._repo.get_policy_decision_hash("decP")
    assert hash_after == hash_before  # the immutable fact is untouched
    assert store.current_version("r4") == version_before  # authority unchanged


def test_replay_05_lineage_complete_queryable_stable(tmp_path):
    store = LearningStore(tmp_path)
    _p, kp = _make_progress("r5", kp_desc="light into chemical energy")
    _seed_open_question(store, "r5", kp, decision_id="decL", expected="light")
    graph = _graph(store)
    out = _run(graph, path_id="r5", stream=_FakeStream(), agent=_FakeAgentLoop(),
               resume_input="light")
    assert out.graded is True
    with store._repo.tx():
        ledger = store._repo.get_evidence_ledger("r5")
        commits = store._repo._conn.execute(
            "SELECT * FROM domain_commits ORDER BY committed_at_ms"
        ).fetchall()
        decs = store._repo._conn.execute("SELECT * FROM policy_decisions").fetchall()
    # Full lineage: decision_id -> action_id -> evidence_id -> commit_id.
    ev = ledger[-1]
    dec_id, action_id = ev["decision_id"], ev["action_id"]
    assert dec_id == "decL" and action_id == "decL:graded"
    assert any(d["decision_id"] == dec_id and d["learner_id"] == "r5" for d in decs)
    commit_row = next(c for c in commits if c["action_id"] == action_id and c["learner_id"] == "r5")
    # Ids are deterministic & recomputable → replay-safe / query-stable.
    assert ev["evidence_id"] == evidence_id("r5", action_id, 0)
    assert commit_row["commit_id"] == commit_id("r5", action_id)


__all__ = []
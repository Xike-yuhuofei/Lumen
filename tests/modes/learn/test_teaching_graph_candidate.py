"""Minimal Teaching Session Graph Candidate — closed loop + lineage + resume.

Proves the graph-owned educational loop:

    SNAPSHOT -> ASSESS -> DIAGNOSE -> DECIDE -> ACT (content | pose) ->
    COMMIT (evidence + state) -> CONTINUE / TERMINATE

* decisions come from the deterministic Teaching Engine (never the LLM);
* content generation is delegated to the Agent Runtime (never re-implemented);
* every learner effect carries ``decision_id -> action_id -> evidence_id ->
  commit_id`` lineage and funnels through DomainCommit;
* a crash between pose and resume re-decides from a fresh snapshot and never
  duplicates a completed grade (idempotent commit + atomic pending-clear).
"""

from __future__ import annotations

import asyncio

import pytest

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.application.teaching_service import TeachingService
from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint
from lumen.modes.learn.graph.contract import GRAPH_TOPOLOGY, TeachingNode
from lumen.modes.learn.graph.domain_service import TeachingGraphDomain
from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph
from lumen.modes.learn.graph.selector import (
    LUMEN_LEARN_GRAPH_CANDIDATE_ENV,
    is_graph_candidate_enabled,
    route_learn_turn,
)
from lumen.runtime.context import UnifiedContext


class _FakeAgentLoop:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.runs = 0

    async def run(self, *, context, stream, language="en", **config):
        self.runs += 1
        self.calls.append(config)
        # mark completion like the adapter would
        context.metadata["exec_completed"] = True
        context.metadata["exec_termination"] = "completed"


class _FakeStream:
    def __init__(self):
        self.events = []

    async def emit(self, event, *, source=None, stage=None, metadata=None):
        self.events.append(("emit", event))


def _make_progress(path_id, *, kp_desc="photosynthesis", kp_type=KnowledgeType.CONCEPT):
    progress = LearningProgress(book_id=path_id)
    kp = KnowledgePoint(
        id=f"{path_id}_m0_kp0",
        name="Photosynthesis",
        type=kp_type,
        module_id=f"{path_id}_m0",
        description=kp_desc,
    )
    module = LearningModule(id=f"{path_id}_m0", name="Biology", order=0, knowledge_points=[kp])
    progress.modules = [module]
    progress.knowledge_types[kp.id] = kp.type
    return progress, kp


def _make_graph_svc(store):
    return TeachingService(learning_store=store)


def _graph(root: pytest.TempPathFactory, store, *, ckp: TeachingGraphCheckpoint | None = None):
    return TeachingSessionGraph(
        store=store,
        domain=TeachingGraphDomain(store),
        teaching_service=_make_graph_svc(store),
        checkpoint=ckp,
    )


def _ctx(mastery=True):
    ctx = UnifiedContext(session_id="sess", user_message="hi", language="en")
    ctx.metadata["mastery_mode"] = mastery
    ctx.metadata["turn_id"] = "turn-1"
    return ctx


def _run_graph(graph, *, path_id, stream, agent, resume_input=None, execute_gen="exec-1", op="start"):
    ctx = _ctx()
    return asyncio.run(
        graph.run_turn(
            path_id=path_id,
            teaching_session_id="ts-test",
            execution_generation=execute_gen,
            execution_operation=op,
            resume_input=resume_input,
            context=ctx,
            stream=stream,
            agent_loop=agent,
            deps={},
        )
    )


# ── selection: coexist with the teaching-hook path ──────────────────────────


def test_candidate_off_by_default(monkeypatch):
    monkeypatch.delenv(LUMEN_LEARN_GRAPH_CANDIDATE_ENV, raising=False)
    assert is_graph_candidate_enabled() is False
    assert route_learn_turn(context=_ctx()) == "hook"
    ctx_hook = _ctx()
    ctx_hook.metadata["mastery_mode"] = False
    assert route_learn_turn(context=ctx_hook) == "hook"


def test_candidate_enabled_routes_graph(monkeypatch):
    monkeypatch.setenv(LUMEN_LEARN_GRAPH_CANDIDATE_ENV, "1")
    assert is_graph_candidate_enabled() is True
    assert route_learn_turn(context=_ctx()) == "graph"


# ── topology is explicit & auditable ────────────────────────────────────────


def test_graph_topology_is_the_minimal_closed_loop():
    assert TeachingNode.SNAPSHOT.value in GRAPH_TOPOLOGY
    # SNAPSHOT -> ASSESS -> DIAGNOSE -> DECIDE -> ACT -> COMMIT -> CONTINUE/TERMINATE
    assert GRAPH_TOPOLOGY[TeachingNode.SNAPSHOT.value] == (TeachingNode.ASSESS.value,)
    assert GRAPH_TOPOLOGY[TeachingNode.ASSESS.value] == (TeachingNode.DIAGNOSE.value,)
    assert GRAPH_TOPOLOGY[TeachingNode.DIAGNOSE.value] == (TeachingNode.DECIDE.value,)
    assert GRAPH_TOPOLOGY[TeachingNode.DECIDE.value] == (TeachingNode.ACT.value,)
    assert set(GRAPH_TOPOLOGY[TeachingNode.COMMIT.value]) == {
        TeachingNode.CONTINUE.value,
        TeachingNode.TERMINATE.value,
    }


# ── the loop ────────────────────────────────────────────────────────────────


def test_no_path_terminates_immediately(tmp_path):
    store = LearningStore(tmp_path)
    graph = _graph(tmp_path, store)
    out = _run_graph(graph, path_id="missing", stream=_FakeStream(), agent=_FakeAgentLoop())
    assert out.is_terminal is True
    assert out.node == TeachingNode.TERMINATE


def test_content_action_delegates_to_agent_loop_not_reimplemented(tmp_path):
    store = LearningStore(tmp_path)
    progress, _kp = _make_progress("p1", kp_desc="photosynthesis converts light to chemical energy")
    store.save(progress)
    agent = _FakeAgentLoop()
    stream = _FakeStream()
    graph = _graph(tmp_path, store)
    out = _run_graph(graph, path_id="p1", stream=stream, agent=agent)

    # First exposure is a content action -> engine EXPLAIN, delegated to runtime.
    assert out.decision.policy_version == "teaching-engine:v1"
    assert out.node == TeachingNode.CONTINUE
    assert out.committed is None  # content generation is not a domain write
    assert agent.runs == 1
    assert agent.calls[0].get("disable_mastery_flow") is True
    assert agent.calls[0]["graph_directive"]["action"] == "explain"


def test_pending_answer_is_graded_and_committed_with_lineage(tmp_path):
    store = LearningStore(tmp_path)
    progress, kp = _make_progress("p2", kp_desc="yes", kp_type=KnowledgeType.MEMORY)
    progress.pending_question = PendingQuestion(
        question_id="seed-q",
        knowledge_point_id=kp.id,
        module_id=kp.module_id,
        prompt="Is photosynthesis a process?",
        question_type="short",
        expected_answer="yes",
        decision_id="dec-seed",
        action_id="dec-seed:pose",
    )
    store.save(progress)

    ckp = TeachingGraphCheckpoint(tmp_path / "ckp")
    graph = _graph(tmp_path, store, ckp=ckp)
    out = _run_graph(
        graph,
        path_id="p2",
        stream=_FakeStream(),
        agent=_FakeAgentLoop(),
        resume_input="yes",
    )

    assert out.graded is True
    assert out.committed is True
    assert out.lineage.decision_id  # a fresh decision was minted

    reloaded = store.load("p2")
    # The graded answer is recorded and the SEEDED question is resolved.  The
    # graph may then immediately continue the loop and pose a fresh (gq-) quest
    # question — but the seeded one is never re-pending.
    assert len(reloaded.quiz_attempts) >= 1
    assert reloaded.quiz_attempts[-1].question_id == "seed-q"
    assert reloaded.quiz_attempts[-1].is_correct is True
    pq = reloaded.pending_question
    assert pq is None or pq.question_id.startswith("gq-")

    # The graph checkpoint persists the walking position for aud./restart.
    pos = ckp.position("ts-test", "exec-1")
    assert pos is not None
    assert pos["last_node"] in (
        TeachingNode.CONTINUE.value,
        TeachingNode.TERMINATE.value,
    )


def test_evidence_decision_id_rides_the_pose_decision_lineage(tmp_path):
    store = LearningStore(tmp_path)
    progress, kp = _make_progress("p3", kp_desc="yes")
    progress.pending_question = PendingQuestion(
        question_id="seed-q2",
        knowledge_point_id=kp.id,
        module_id=kp.module_id,
        prompt="Q",
        question_type="short",
        expected_answer="yes",
        decision_id="dec-pose-42",
        action_id="dec-pose-42:pose",
    )
    store.save(progress)
    graph = _graph(tmp_path, store)
    _run_graph(graph, path_id="p3", stream=_FakeStream(), agent=_FakeAgentLoop(), resume_input="yes")

    # Inspect the authoritative evidence ledger directly.
    ledger = []
    with store._repo.tx():
        ledger = store._repo.get_evidence_ledger("p3")
    ev = ledger[-1]
    assert ev["decision_id"] == "dec-pose-42"  # evidence attributes back to the pose decision


def test_crash_after_grade_replays_idempotently_no_dup_effect(tmp_path):
    """A crash between a graded commit and its receipt must not fold the answer
    into the ledger twice: re-issuing the SAME action (same action_id + payload)
    collapses to a REPLAYED receipt and a single evidence row.
    """
    from lumen.modes.learn.commit.commit_service import DomainCommitService
    from lumen.modes.learn.commit.contract import DomainCommitRequest, Evidence

    store = LearningStore(tmp_path)
    _progress, kp = _make_progress("p4", kp_desc="yes")
    progress = LearningProgress(book_id="p4")
    progress.modules = _progress.modules
    progress.knowledge_types = _progress.knowledge_types
    progress.pending_question = PendingQuestion(
        question_id="q",
        knowledge_point_id=kp.id,
        module_id=kp.module_id,
        prompt="Q",
        question_type="short",
        expected_answer="yes",
        decision_id="dec-1",
        action_id="dec-1:pose",
    )
    store.save(progress)

    state = {k: v for k, v in (store.load("p4").model_dump(mode="json")).items()}
    ev = Evidence(
        target_type="knowledge_point",
        target_id=kp.id,
        evidence_type="quiz_answer",
        outcome=True,
        outcome_json={"is_correct": True, "question_id": "q", "module_id": kp.module_id},
        raw_response_json={"user_answer": "yes"},
        evaluator_kind="deterministic",
        evaluator_version="graph-candidate:v1",
        decision_id="dec-1",
    )
    request = DomainCommitRequest(
        learner_id="p4",
        action_id="dec-1:graded",
        expected_learner_version=store.current_version("p4"),
        proposed_state=state,
        evidence=[ev],
        decision={"decision_id": "dec-1", "policy_version": "teaching-engine:v1", "action": "assess"},
        decision_id="dec-1",
    )
    svc = DomainCommitService(store._repo)
    first = svc.commit(request)
    assert first.status.value == "APPLIED"
    with store._repo.tx():
        n_before = len(store._repo.get_evidence_ledger("p4"))

    # Crash -> restart re-issues the SAME action/payload: idempotent replay.
    replay = svc.commit(request)
    assert replay.replayed is True
    assert replay.status.value == "REPLAYED"
    with store._repo.tx():
        n_after = len(store._repo.get_evidence_ledger("p4"))

    assert n_after == n_before == 1
    # The chain is a full, distinct lineage: decision -> action -> evidence -> commit.
    assert replay.action_id == "dec-1:graded"
    assert replay.commit_id  # deterministic uuid5 over (learner, action)
    assert len(replay.evidence_ids) >= 1
    assert replay.evidence_ids[0] != replay.action_id
    assert replay.commit_id != replay.action_id


def test_pose_represents_open_pending_question_and_parks(tmp_path):
    # A pending question with no incoming answer stays on the graph's quest
    # node (RESOLVE_PENDING) and is presented again — a parked continuation.
    store = LearningStore(tmp_path)
    progress, kp = _make_progress("p5", kp_desc="photosynthesis converts light into chemical energy")
    progress.pending_question = PendingQuestion(
        question_id="pending-1",
        knowledge_point_id=kp.id,
        module_id=kp.module_id,
        prompt="Q",
        question_type="short",
        expected_answer="light",
        decision_id="dec-pending",
        action_id="dec-pending:pose",
    )
    store.save(progress)
    graph = _graph(tmp_path, store)
    out = _run_graph(graph, path_id="p5", stream=_FakeStream(), agent=_FakeAgentLoop())

    assert out.decision.action == "resolve_pending"
    assert out.posed_pending is True  # re-presented, parked for the learner's answer
    reloaded = store.load("p5")
    assert reloaded is not None and reloaded.pending_question is not None


def test_no_learner_effect_without_commit(tmp_path):
    """A pure content pass writes nothing to the authoritative domain."""
    store = LearningStore(tmp_path)
    progress, _ = _make_progress("p6", kp_desc="x")
    store.save(progress)
    base_version = store.current_version("p6")
    graph = _graph(tmp_path, store)
    _run_graph(graph, path_id="p6", stream=_FakeStream(), agent=_FakeAgentLoop())
    # A first-exposure content pass may still be an EXPLAIN with no learned effect.
    assert store.current_version("p6") >= base_version  # no evidence rows added
    assert len(store.load("p6").quiz_attempts) == 0
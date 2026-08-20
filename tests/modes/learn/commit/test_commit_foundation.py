"""P0 hard gates for the Learner Domain Commit Foundation.

Implements the design report's test matrix (§12): TX / CAS / MAS / CR / OB /
MIG, plus a funnel check that authoritative mastery writes go through the
canonical commit (no JSON save() bypass).

Correctness model under test:
``at-least-once execution + idempotent atomic domain commit + optimistic
concurrency``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.application.service import LearningService
from lumen.modes.learn.commit.commit_service import DomainCommitService, build_request_hash
from lumen.modes.learn.commit.contract import (
    DomainCommitRequest,
    Evidence,
    IdempotencyKeyReuse,
    OutboxIntent,
)
from lumen.modes.learn.commit.identity import stable_hash
from lumen.modes.learn.commit.migration import migrate_learning_json, verify_migration
from lumen.modes.learn.commit.outbox import OutboxDispatcher, OutboxPayloadConflict
from lumen.modes.learn.commit.repository import LearnerDomainRepository
from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from lumen.modes.learn.policy.mastery import compute_mastery


def _repo(tmp_path):
    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    return repo


def _svc(tmp_path):
    return DomainCommitService(_repo(tmp_path))


def _progress(book="b", kp="kp1", kp_type=KnowledgeType.CONCEPT) -> LearningProgress:
    lp = LearningProgress(book_id=book)
    lp.modules = [
        LearningModule(
            id="m1",
            name="M",
            order=0,
            knowledge_points=[KnowledgePoint(id=kp, name=kp, type=kp_type, module_id="m1")],
        )
    ]
    lp.knowledge_types[kp] = kp_type
    return lp


def _quiz_req(prog, *, action="a1", expected=0, correct=True, q="q1", cid=""):
    return DomainCommitRequest(
        learner_id=prog.book_id,
        action_id=action,
        expected_learner_version=expected,
        proposed_state=prog.model_dump(mode="json"),
        evidence=[
            Evidence(
                target_type="knowledge_point",
                target_id="kp1",
                evidence_type="quiz_answer",
                outcome=correct,
                outcome_json={
                    "is_correct": correct,
                    "question_id": q,
                    "module_id": "m1",
                    "question_kind": "recall",
                },
                raw_response_json={"user_answer": "ans"},
                observed_at_ms=1_000,
            )
        ],
        decision_id=cid or "",
        decision={"policy_version": "p1"} if cid else None,
    )


# ── TX: transaction / idempotency ─────────────────────────────────────────


def test_tx01_same_action_replayed_has_single_effect(tmp_path):
    svc = _svc(tmp_path)
    r1 = svc.commit(_quiz_req(_progress()))
    r2 = svc.commit(_quiz_req(_progress()))
    assert r1.status.value == "APPLIED"
    assert r2.status.value == "REPLAYED"
    assert r1.resulting_version == r2.resulting_version == 1
    assert r1.commit_id == r2.commit_id
    # single effect: one evidence, one commit, no version drift.
    ledger = svc.repository.get_evidence_ledger("b")
    commits = svc.repository._conn.execute("SELECT * FROM domain_commits").fetchall()
    assert len(ledger) == 1
    assert len(commits) == 1


def test_tx03_same_action_different_payload_rejected(tmp_path):
    svc = _svc(tmp_path)
    svc.commit(_quiz_req(_progress(), action="a1"))
    with pytest.raises(IdempotencyKeyReuse):
        svc.commit(_quiz_req(_progress(), action="a1", correct=False))


def test_tx02_concurrent_same_action_unique_adjudicates(tmp_path):
    """Concurrent writers (separate connections = separate "sessions")
    issuing the same action id → exactly one effect, no duplicate."""
    import threading

    db = tmp_path / "learner.db"
    errors = []  # noqa
    outcomes: "list" = []

    def run():
        svc = DomainCommitService(LearnerDomainRepository(db_path=db))
        try:
            svc.commit(_quiz_req(_progress(), action="a1"))
            outcomes.append("ok")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(str(type(exc).__name__))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # exactly one durable effect regardless of how many callers succeeded.
    repo = LearnerDomainRepository(db_path=db)
    assert len(repo.get_evidence_ledger("b")) == 1
    assert len(repo._conn.execute("SELECT * FROM domain_commits").fetchall()) == 1


# ── CAS: optimistic concurrency / reconciliation ─────────────────────────


def test_cas01_two_sessions_same_version_reconcile(tmp_path):
    svc = _svc(tmp_path)
    base = _progress(kp_type=KnowledgeType.MEMORY)
    svc.commit(_quiz_req(base, action="seed", expected=0, q="seed"))
    progA = LearningProgress.model_validate(svc.get_state("b"))
    progB = LearningProgress.model_validate(svc.get_state("b"))
    rb = svc.commit(_quiz_req(progB, action="B", expected=1, correct=True, q="qb"))
    ra = svc.commit(_quiz_req(progA, action="A", expected=1, correct=False, q="qa"))
    assert rb.status.value == "APPLIED" and rb.resulting_version == 2
    assert ra.status.value == "APPLIED_RECONCILED" and ra.resulting_version == 3
    st = svc.get_state("b")
    assert len(st["quiz_attempts"]) == 3  # seed + both sessions
    assert st["mastery_levels"]["kp1"] == compute_mastery([True, True, False])


def test_cas02_evidence_not_lost_on_conflict(tmp_path):
    svc = _svc(tmp_path)
    base = _progress(kp_type=KnowledgeType.MEMORY)
    svc.commit(_quiz_req(base, action="seed", q="seed"))
    progA = LearningProgress.model_validate(svc.get_state("b"))
    progB = LearningProgress.model_validate(svc.get_state("b"))
    svc.commit(_quiz_req(progB, action="B", expected=1, correct=True, q="b"))
    ra = svc.commit(_quiz_req(progA, action="A", expected=1, correct=False, q="a"))
    assert ra.status.value == "APPLIED_RECONCILED"
    assert len(svc.repository.get_evidence_ledger("b")) == 3


def test_cas03_stale_mastery_snapshot_ignored(tmp_path):
    svc = _svc(tmp_path)
    base = _progress(kp_type=KnowledgeType.MEMORY)
    svc.commit(_quiz_req(base, action="seed", correct=True, q="seed"))  # mastery 0.5
    stale = _progress(kp_type=KnowledgeType.MEMORY)
    stale.mastery_levels["kp1"] = 1.0
    stale.quiz_attempts = []
    svc.commit(_quiz_req(stale, action="A", expected=1, correct=True, q="a"))
    st = svc.get_state("b")
    # derived mastery recomputed from the two real evidences, not the stale 1.0
    assert st["mastery_levels"]["kp1"] == compute_mastery([True, True])


def test_cas04_stale_decision_marked_and_requires_redecision(tmp_path):
    svc = _svc(tmp_path)
    base = _progress(kp_type=KnowledgeType.MEMORY)
    svc.commit(_quiz_req(base, action="seed", q="seed"))
    progA = LearningProgress.model_validate(svc.get_state("b"))
    progB = LearningProgress.model_validate(svc.get_state("b"))
    svc.commit(_quiz_req(progB, action="B", expected=1, correct=True, q="b", cid="dec-B"))
    ra = svc.commit(_quiz_req(progA, action="A", expected=1, correct=False, q="a", cid="dec-A"))
    assert ra.status.value == "APPLIED_RECONCILED"
    assert ra.requires_redecision is True
    assert ra.decision_stale is True
    stale = svc.repository._conn.execute(
        "SELECT * FROM policy_decision_events WHERE decision_id='dec-A' AND kind='stale'"
    ).fetchall()
    assert len(stale) == 1


# ── MAS: mastery provenance / qualitative reducer ────────────────────────

def test_mas02_qualitative_pass_then_fail(tmp_path):
    svc = _svc(tmp_path)
    prog = _progress()
    svc.commit(_prog_req(prog, "seed", 0))
    svc.commit(_feynman_req(prog, "fa", True, expected=1))
    svc.commit(_feynman_req(prog, "fb", False, expected=2))
    st = svc.get_state("b")
    assert st["qualitative_mastery"]["kp1"] is False
    assert st["mastery_levels"]["kp1"] <= 0.4
    # two evaluator judgements retained in the ledger (seed was state-only)
    assert len(svc.repository.get_evidence_ledger("b")) == 2


def test_mas03_qualitative_fail_then_pass(tmp_path):
    svc = _svc(tmp_path)
    prog = _progress()
    svc.commit(_prog_req(prog, "seed", 0))
    svc.commit(_feynman_req(prog, "f1", False, expected=1))
    svc.commit(_feynman_req(prog, "f2", True, expected=2))
    st = svc.get_state("b")
    assert st["qualitative_mastery"]["kp1"] is True
    assert st["mastery_levels"]["kp1"] == 1.0
    ev = svc.repository.get_evidence_ledger("b")
    assert len([e for e in ev if e["evidence_type"] == "feynman_explanation"]) == 2


def _prog_req(prog, action, expected):
    return DomainCommitRequest(
        learner_id=prog.book_id, action_id=action, expected_learner_version=expected,
        proposed_state=prog.model_dump(mode="json"),
    )


def _feynman_req(prog, action, passed, expected):
    return DomainCommitRequest(
        learner_id=prog.book_id,
        action_id=action,
        expected_learner_version=expected,
        proposed_state=prog.model_dump(mode="json"),
        evidence=[
            Evidence(
                target_type="knowledge_point",
                target_id="kp1",
                evidence_type="feynman_explanation",
                outcome=bool(passed),
                outcome_json={
                    "passed": bool(passed),
                    "question_id": "feynman:kp1",
                    "module_id": "m1",
                    "question_kind": "application",
                },
                raw_response_json={"user_answer": "explanation"},
                evaluator_kind="llm",
                evaluator_version="v1",
                observed_at_ms=1000 + int(hash(action)),
            )
        ],
    )


# ── CR: crash / fault injection ──────────────────────────────────────────


def test_cr02_mid_transaction_rollback_no_half_write(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    repo = svc.repository
    base = _progress()
    svc.commit(_prog_req(base, "seed", 0))

    def boom(*_a, **_k):
        raise RuntimeError("simulated kill after evidence insert")

    monkeypatch.setattr(repo, "insert_learner_event", boom)
    with pytest.raises(RuntimeError):
        svc.commit(_quiz_req(base, action="killme", expected=1, correct=True, q="k"))
    # nothing half-written: no evidence, no commit, version unchanged
    agg = repo.get_aggregate("b")
    assert agg["learner_version"] == 1
    assert len(repo.get_evidence_ledger("b")) == 0
    assert repo._conn.execute(
        "SELECT * FROM domain_commits WHERE action_id='killme'"
    ).fetchone() is None
    assert repo.integrity_ok()


def test_cr04_replay_after_lost_response(tmp_path):
    svc = _svc(tmp_path)
    r1 = svc.commit(_quiz_req(_progress(), action="a1"))
    # simulate customer lost the response: replay by the same action id
    r2 = svc.replay("b", "a1")
    assert r2 is not None
    assert r2.commit_id == r1.commit_id
    assert r2.status.value == "REPLAYED"
    assert r2.resulting_version == r1.resulting_version
    # no additional domain effect
    assert svc.repository.current_version("b") == r1.resulting_version


def test_cr05_integrity_after_many_commits(tmp_path):
    svc = _svc(tmp_path)
    base = _progress()
    prev = 0
    for i in range(5):
        r = svc.commit(_quiz_req(base, action=f"a{i}", expected=prev, correct=(i % 2 == 0)))
        prev = r.resulting_version
    assert svc.repository.integrity_ok()


# ── OB: question-bank transactional outbox ───────────────────────────────

def _chat_session(tmp_path):
    from lumen.runtime.session.sqlite_store import SQLiteSessionStore

    chat = tmp_path / "chat.db"
    store = SQLiteSessionStore(db_path=chat)
    import asyncio

    session = asyncio.run(store.create_session(title="s"))
    return session["id"], chat


def _grade_with_outbox(prog, action, expected, chat_payload):
    return DomainCommitRequest(
        learner_id=prog.book_id,
        action_id=action,
        expected_learner_version=expected,
        proposed_state=prog.model_dump(mode="json"),
        evidence=[
            Evidence(
                target_type="knowledge_point",
                target_id="kp1",
                evidence_type="quiz_answer",
                outcome=True,
                outcome_json={"is_correct": True, "question_id": "q1", "module_id": "m1"},
                raw_response_json={"user_answer": "ans"},
            )
        ],
        outbox=[OutboxIntent(payload=chat_payload)],
    )


def test_ob01_domain_commits_even_when_target_unwritable(tmp_path):
    svc = _svc(tmp_path)
    repo = svc.repository
    session_id, _ = _chat_session(tmp_path)
    payload = {"session_id": session_id, "turn_id": "t", "question_id": "q1"}
    svc.commit(_grade_with_outbox(_progress(), "a1", 0, payload))
    # block the target: chat path's parent is a regular file
    blocked = tmp_path / "blocked"
    blocked.write_text("x")
    disp = OutboxDispatcher(repository=repo, chat_db_path=blocked / "chat.db")
    stats = disp.dispatch()
    assert stats["retryable_fail"] == 1
    row = repo.outbox_row(disp.pending()[0]["event_id"] if False else _any_outbox(repo))
    assert row["delivered_at_ms"] is None  # still pending & durable


def _any_outbox(repo):
    row = repo._conn.execute("SELECT event_id FROM outbox_events LIMIT 1").fetchone()
    return row["event_id"]


def test_ob02_replay_after_delivered_mark_lost_is_idempotent(tmp_path):
    svc = _svc(tmp_path)
    repo = svc.repository
    session_id, chat = _chat_session(tmp_path)
    payload = {
        "session_id": session_id,
        "turn_id": "t",
        "question_id": "q1",
        "question": "Q?",
        "is_correct": True,
        "user_answer": "ans",
    }
    svc.commit(_grade_with_outbox(_progress(), "a1", 0, payload))
    disp = OutboxDispatcher(repository=repo, chat_db_path=chat)
    stats = disp.dispatch()
    assert stats["ok"] == 1
    # simulate crash BETWEEN target write and source mark: mark delivered lost,
    # outbox row still pending, but the target already has the projection.
    event_id = _any_outbox(repo)
    repo._conn.execute(
        "UPDATE outbox_events SET delivered_at_ms=NULL WHERE event_id=?", (event_id,)
    )
    repo._conn.commit()
    stats2 = disp.dispatch()
    assert stats2["ok"] == 1
    # no duplicate question-bank effect on replay (source_event_id receipt folds)
    import sqlite3

    conn = sqlite3.connect(str(chat))
    conn.row_factory = sqlite3.Row
    cnt = conn.execute(
        "SELECT COUNT(*) c FROM notebook_entries WHERE question_id='q1'"
    ).fetchone()["c"]
    conn.close()
    assert cnt == 1


def test_ob03_payload_key_conflict_hard_fails(tmp_path):
    svc = _svc(tmp_path)
    repo = svc.repository
    session_id, chat = _chat_session(tmp_path)
    payload = {"session_id": session_id, "turn_id": "t", "question_id": "q1",
               "question": "Q?", "is_correct": True}
    svc.commit(_grade_with_outbox(_progress(), "a1", 0, payload))
    disp = OutboxDispatcher(repository=repo, chat_db_path=chat)
    disp.dispatch()
    # simulate replay of the same outbox event with a DIFFERENT payload hash
    event_id = _any_outbox(repo)
    repo._conn.execute(
        "UPDATE outbox_events SET payload_hash=?, delivered_at_ms=NULL WHERE event_id=?",
        ("tampered-hash", event_id),
    )
    repo._conn.commit()
    stats = disp.dispatch()
    assert stats["retryable_fail"] == 1  # conflict surfaced, never silent overwrite


def test_ob05_session_deleted_is_durable_failure(tmp_path):
    svc = _svc(tmp_path)
    repo = svc.repository
    session_id, chat = _chat_session(tmp_path)
    payload = {"session_id": session_id, "turn_id": "t", "question_id": "q1"}
    svc.commit(_grade_with_outbox(_progress(), "a1", 0, payload))
    # session no longer exists
    from lumen.runtime.session.sqlite_store import SQLiteSessionStore

    st = SQLiteSessionStore(db_path=chat)
    with st._connect() as conn:
        conn.execute("DELETE FROM sessions")
    disp = OutboxDispatcher(repository=repo, chat_db_path=chat)
    stats = disp.dispatch()
    assert stats["permanent_fail"] == 1
    row = repo.outbox_row(_any_outbox(repo))
    assert "no longer exists" in row["last_error"]
    assert row["delivered_at_ms"] is None


# ── MIG: JSON migration ──────────────────────────────────────────────────


def _write_legacy_json(root: "Path", progress: LearningProgress):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{progress.book_id}.json").write_text(
        json.dumps(progress.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )


def test_mig01_full_migration_round_trips(tmp_path):
    root = tmp_path / "learning"
    lp = _progress(book="legacy", kp_type=KnowledgeType.MEMORY)
    lp.version = 7
    lp.mastery_levels["kp1"] = 0.6
    lp.quiz_attempts = [
        # one deterministic quiz + one repeated feynman qualitative judgement
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="qA", knowledge_point_id="kp1", module_id="m1", is_correct=True
        ),
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="feynman:kp1", knowledge_point_id="kp1", module_id="m1",
            is_correct=True, question_kind="application"
        ),
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="feynman:kp1", knowledge_point_id="kp1", module_id="m1",
            is_correct=False, question_kind="application"
        ),
    ]
    _write_legacy_json(root, lp)
    import uuid as _u

    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    res = migrate_learning_json(root, repo)
    assert res.imported == ["legacy"]
    assert len(repo.get_evidence_ledger("legacy")) == len(lp.quiz_attempts)
    # legacy version preserved; next commit bumps +1
    assert repo.get_aggregate("legacy")["learner_version"] == 7
    agg = repo.get_aggregate("legacy")
    state = json.loads(agg["state_json"])
    assert state["mastery_levels"]["kp1"] == 0.6
    ver = verify_migration(root, repo)
    assert ver["ok"] is True


def test_mig02_rerun_is_noop(tmp_path):
    root = tmp_path / "learning"
    lp = _progress(book="l1")
    _write_legacy_json(root, lp)
    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    migrate_learning_json(root, repo)
    before = len(repo.get_evidence_ledger("l1"))
    migrate_learning_json(root, repo)  # idempotent
    assert len(repo.get_evidence_ledger("l1")) == before
    assert len(repo._conn.execute("SELECT * FROM migration_log").fetchall()) == 1


def test_mig03_corrupt_json_fails_closed(tmp_path):
    root = tmp_path / "learning"
    root.mkdir(parents=True, exist_ok=True)
    (root / "bad.json").write_text("{not json", encoding="utf-8")
    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    res = migrate_learning_json(root, repo)
    assert res.imported == []
    assert len(res.errors) == 1
    # authority not switched: no aggregate imported
    assert repo.get_aggregate("bad") is None
    # source file untouched
    assert (root / "bad.json").read_text(encoding="utf-8") == "{not json"


def test_mig_rollback_returns_to_json_and_is_reimportable(tmp_path):
    """Rollback drops the imported authority rows (JSON stays as the backup)
    and a subsequent migration re-imports cleanly — no split-brain."""
    from lumen.modes.learn.commit.migration import rollback_migration

    root = tmp_path / "learning"
    lp = _progress(book="rb")
    lp.version = 3
    lp.quiz_attempts = [
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="q1", knowledge_point_id="kp1", module_id="m1", is_correct=True
        )
    ]
    _write_legacy_json(root, lp)
    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    migrate_learning_json(root, repo)
    assert repo.get_aggregate("rb") is not None
    source_before = (root / "rb.json").read_bytes()
    # rollback clears the imported authority; the JSON backup is untouched
    rollback_migration(["rb"], repo)
    assert repo.get_aggregate("rb") is None
    assert (root / "rb.json").read_bytes() == source_before
    # no split-brain: no import marker is still claiming 'rb' as migrated
    assert "rb" not in repo.migrated_learner_ids()
    # re-import works cleanly from the same untouched JSON
    migrate_learning_json(root, repo)
    assert repo.get_aggregate("rb") is not None
    assert len(repo.get_evidence_ledger("rb")) == 1


def test_mig05_repeated_feynman_ids_distinct(tmp_path):
    root = tmp_path / "learning"
    lp = _progress(book="f")
    lp.quiz_attempts = [
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="feynman:kp1", knowledge_point_id="kp1", module_id="m1",
            is_correct=True
        ),
        __import__("lumen.modes.learn.domain.models", fromlist=["QuizAttempt"]).QuizAttempt(
            question_id="feynman:kp1", knowledge_point_id="kp1", module_id="m1",
            is_correct=False
        ),
    ]
    _write_legacy_json(root, lp)
    repo = LearnerDomainRepository(db_path=tmp_path / "learner.db")
    migrate_learning_json(root, repo)
    ev = repo.get_evidence_ledger("f")
    assert len({e["evidence_id"] for e in ev}) == len(ev)  # all distinct


def test_funnel_no_save_bypass(tmp_path):
    """grade_and_record must write through the canonical commit (evidence +
    CAS), never a blind JSON save()."""
    store = LearningStore(root=tmp_path)
    svc = LearningService(store)
    prog = _progress()
    store.save(prog)
    svc.grade_and_record(
        prog,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="right",
        expected_answer="right",
    )
    ledger = store._repo.get_evidence_ledger(prog.book_id)
    assert len(ledger) == 1
    commits = store._repo._conn.execute("SELECT * FROM domain_commits").fetchall()
    assert len(commits) >= 1
    # no JSON progress file is ever written (single authority)
    assert not (tmp_path / f"{prog.book_id}.json").exists()
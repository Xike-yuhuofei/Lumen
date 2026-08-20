"""Persistence for the Phase 1 Certification store (SQLite-backed).

Canonical home: ``lumen/cert``.

Design intent (Data Contract):
* Teaching trace is **append-only** — TurnArtifact / EvaluationResult rows are
  never ``UPDATE``d in a way that rewrites seen evidence.
* Raw Evaluation is stored separately from the Final Turn Status; the final
  status is written only by the controller after Failure Review.
* Candidate / Context must never be **silently overwritten**: writing a
  CandidateManifest / ContextManifest whose ``content_digest`` differs from the
  one its id was first issued under is rejected.
* Every concept is traceable (episode -> turns -> evaluations -> failure cases
  -> regression cases -> certifications).

Storage is deliberately self-contained (no dependency on the learner / session
stores) so certification is reproducible and isolated, while reusing the same
SQLite conventions as ``lumen.modes.learn.commit.repository``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from .models import (
    CandidateManifest,
    ContextManifest,
    Episode,
    EpisodeEnd,
    EvaluationResult,
    FailureCase,
    FailureReview,
    RegressionCase,
    TransitionLog,
    TurnArtifact,
    content_digest,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cert_candidates (
    id TEXT PRIMARY KEY,
    parent_candidate_id TEXT,
    content_digest TEXT NOT NULL,
    tutor_config TEXT NOT NULL,
    prompt_override TEXT NOT NULL,
    temperature REAL NOT NULL,
    created_at REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS cert_contexts (
    trajectory_context_id TEXT NOT NULL,
    evaluation_context_id TEXT NOT NULL,
    trajectory_digest TEXT NOT NULL,
    evaluation_digest TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (trajectory_context_id, evaluation_context_id)
);
CREATE TABLE IF NOT EXISTS cert_episodes (
    episode_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    trajectory_context_id TEXT NOT NULL,
    evaluation_context_id TEXT NOT NULL,
    status TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS cert_turn_artifacts (
    episode_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    learner_utterance TEXT NOT NULL,
    tutor_action TEXT NOT NULL,
    prior_conversation TEXT NOT NULL,
    hidden_learner_state TEXT NOT NULL,
    final_status TEXT,
    PRIMARY KEY (episode_id, turn_index)
);
CREATE TABLE IF NOT EXISTS cert_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    evaluator_id TEXT NOT NULL,
    evaluator_perspective TEXT NOT NULL,
    evaluation_status TEXT NOT NULL,
    decision TEXT,
    criterion_id TEXT,
    affected_turn INTEGER,
    evidence TEXT,
    severity TEXT,
    reason TEXT,
    confidence REAL,
    raw TEXT
);
CREATE TABLE IF NOT EXISTS cert_failure_reviews (
    failure_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    attribution TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    reviewed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cert_failure_cases (
    failure_case_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    affected_turn INTEGER NOT NULL,
    frozen_checkpoint TEXT NOT NULL,
    status TEXT NOT NULL,
    regression_case_id TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cert_regression_cases (
    regression_case_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    checker TEXT NOT NULL,
    data TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cert_transitions (
    transition_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cert_turn_episode ON cert_turn_artifacts(episode_id);
CREATE INDEX IF NOT EXISTS idx_cert_eval_turn ON cert_evaluations(episode_id, turn_index);
"""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class CertificationStoreError(Exception):
    """Store-level integrity violation (e.g. silent overwrite attempt)."""


class CertificationStore:
    """SQLite store for the Phase 1 certification subsystem.

    Thread-safety: SQLite connections are not safe to share across async tasks
    without care; the store uses ``asyncio``-transparent ``to_thread`` friendly
    synchronous methods behind a ``threading.Lock``, mirroring the repository
    pattern used elsewhere in Lumen.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(_SCHEMA)
                self._migrate_contexts_composite_key(conn)
                conn.commit()
            finally:
                conn.close()

    def _migrate_contexts_composite_key(self, conn: sqlite3.Connection) -> None:
        """Migrate a legacy ``cert_contexts`` whose PK was only the trajectory id.

        Phase 1 requires an **Evaluation-only Change** path: the immutable
        trajectory may carry *more than one* EvaluationContext (a rubric /
        evaluator-config change re-adjudicates the same trace). The old schema
        made ``trajectory_context_id`` the sole PRIMARY KEY, which silently
        forbade a second evaluation context per trajectory. Rebuild the table
        keyed on ``(trajectory_context_id, evaluation_context_id)`` when needed.
        """
        pk = conn.execute(
            "SELECT name FROM pragma_table_info('cert_contexts') "
            "WHERE pk > 0 ORDER BY pk"
        ).fetchall()
        pk_cols = [r["name"] for r in pk]
        if len(pk_cols) == 2 or "trajectory_context_id" not in pk_cols:
            return  # already composite (or unexpected) — nothing to do
        conn.executescript(
            """
            CREATE TABLE cert_contexts_migrated (
                trajectory_context_id TEXT NOT NULL,
                evaluation_context_id TEXT NOT NULL,
                trajectory_digest TEXT NOT NULL,
                evaluation_digest TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (trajectory_context_id, evaluation_context_id)
            );
            INSERT OR IGNORE INTO cert_contexts_migrated
                (trajectory_context_id, evaluation_context_id, trajectory_digest,
                 evaluation_digest, created_at)
                SELECT trajectory_context_id, evaluation_context_id, trajectory_digest,
                       evaluation_digest, created_at FROM cert_contexts;
            DROP TABLE cert_contexts;
            ALTER TABLE cert_contexts_migrated RENAME TO cert_contexts;
            """
        )

    # ── Candidate / Context (no silent overwrite) ───────────────────────────

    def put_candidate(self, candidate: CandidateManifest) -> None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT content_digest FROM cert_candidates WHERE id=?",
                    (candidate.effective_candidate_id,),
                ).fetchone()
                if row is not None:
                    if row["content_digest"] != candidate.content_digest:
                        raise CertificationStoreError(
                            f"Candidate silent-overwrite rejected: {candidate.effective_candidate_id}"
                        )
                    return  # identical digest => idempotent re-put; do not overwrite fields
                conn.execute(
                    "INSERT INTO cert_candidates"
                    "(id,parent_candidate_id,content_digest,tutor_config,prompt_override,"
                    "temperature,created_at,active) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        candidate.effective_candidate_id,
                        candidate.parent_candidate_id,
                        candidate.content_digest,
                        _json_dumps(candidate.tutor_config),
                        candidate.prompt_override,
                        candidate.temperature,
                        candidate.created_at,
                        1 if candidate.active else 0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_candidate(self, candidate_id: str) -> CandidateManifest | None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM cert_candidates WHERE id=?", (candidate_id,)
                ).fetchone()
                if row is None:
                    return None
                return CandidateManifest(
                    effective_candidate_id=row["id"],
                    parent_candidate_id=row["parent_candidate_id"],
                    content_digest=row["content_digest"],
                    tutor_config=json.loads(row["tutor_config"]),
                    prompt_override=row["prompt_override"],
                    temperature=float(row["temperature"]),
                    created_at=float(row["created_at"]),
                    active=bool(row["active"]),
                )
            finally:
                conn.close()

    def put_context(self, context: ContextManifest) -> None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT trajectory_digest, evaluation_digest FROM cert_contexts "
                    "WHERE trajectory_context_id=? AND evaluation_context_id=?",
                    (context.trajectory_context_id, context.evaluation_context_id),
                ).fetchone()
                if row is not None:
                    if (
                        row["trajectory_digest"] != context.trajectory_digest
                        or row["evaluation_digest"] != context.evaluation_digest
                    ):
                        raise CertificationStoreError(
                            "Context silent-overwrite rejected: trajectory/evaluation digest drift"
                        )
                    return
                conn.execute(
                    "INSERT INTO cert_contexts"
                    "(trajectory_context_id,evaluation_context_id,trajectory_digest,"
                    "evaluation_digest,created_at) VALUES (?,?,?,?,?)",
                    (
                        context.trajectory_context_id,
                        context.evaluation_context_id,
                        context.trajectory_digest,
                        context.evaluation_digest,
                        context.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_context(self, trajectory_context_id: str, evaluation_context_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM cert_contexts WHERE trajectory_context_id=? "
                    "AND evaluation_context_id=?",
                    (trajectory_context_id, evaluation_context_id),
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    # ── Episodes / Turns (append-only trace) ────────────────────────────────

    def create_episode(self, episode: Episode) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_episodes"
                    "(episode_id,candidate_id,trajectory_context_id,evaluation_context_id,"
                    "status,turn_count,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        episode.episode_id,
                        episode.candidate_id,
                        episode.trajectory_context_id,
                        episode.evaluation_context_id,
                        episode.status.value if isinstance(episode.status, EpisodeEnd) else str(episode.status),
                        episode.turn_count,
                        episode.started_at,
                        episode.finished_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM cert_episodes WHERE episode_id=?", (episode_id,)
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def finish_episode(self, episode_id: str, status: EpisodeEnd, turn_count: int) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE cert_episodes SET status=?, turn_count=?, finished_at=? WHERE episode_id=?",
                    (status.value, turn_count, 0.0, episode_id),
                )
                conn.commit()
            finally:
                conn.close()

    def append_turn(self, turn: TurnArtifact) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_turn_artifacts"
                    "(episode_id,turn_index,learner_utterance,tutor_action,prior_conversation,"
                    "hidden_learner_state,final_status) VALUES (?,?,?,?,?,?,?)",
                    (
                        turn.episode_id,
                        turn.turn_index,
                        turn.learner_utterance,
                        turn.tutor_action,
                        _json_dumps(turn.prior_conversation),
                        _json_dumps(turn.hidden_learner_state),
                        turn.final_status.value if turn.final_status else None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def set_turn_final_status(self, episode_id: str, turn_index: int, status: str) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE cert_turn_artifacts SET final_status=? "
                    "WHERE episode_id=? AND turn_index=?",
                    (status, episode_id, turn_index),
                )
                conn.commit()
            finally:
                conn.close()

    def get_turns(self, episode_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM cert_turn_artifacts WHERE episode_id=? ORDER BY turn_index",
                    (episode_id,),
                ).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["prior_conversation"] = json.loads(d["prior_conversation"])
                    d["hidden_learner_state"] = json.loads(d["hidden_learner_state"])
                    out.append(d)
                return out
            finally:
                conn.close()

    # ── Evaluations ─────────────────────────────────────────────────────────

    def append_evaluation(self, result: EvaluationResult) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_evaluations"
                    "(evaluation_id,episode_id,turn_index,evaluator_id,evaluator_perspective,"
                    "evaluation_status,decision,criterion_id,affected_turn,evidence,severity,"
                    "reason,confidence,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        result.evaluation_id,
                        result.episode_id,
                        result.turn_index,
                        result.evaluator_id,
                        result.evaluator_perspective,
                        result.evaluation_status.value,
                        result.decision.value if result.decision else None,
                        result.criterion_id,
                        result.affected_turn,
                        result.evidence,
                        result.severity,
                        result.reason,
                        result.confidence,
                        _json_dumps(result.raw),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_evaluations(self, episode_id: str, turn_index: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._conn()
            try:
                if turn_index is None:
                    rows = conn.execute(
                        "SELECT * FROM cert_evaluations WHERE episode_id=? ORDER BY turn_index",
                        (episode_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM cert_evaluations WHERE episode_id=? AND turn_index=? "
                        "ORDER BY evaluator_id",
                        (episode_id, turn_index),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ── Failure Reviews / Failure Cases ─────────────────────────────────────

    def append_failure_review(self, review: FailureReview) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_failure_reviews"
                    "(failure_id,episode_id,turn_index,attribution,reasoning,reviewed_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        review.failure_id,
                        review.episode_id,
                        review.turn_index,
                        review.attribution.value,
                        review.reasoning,
                        review.reviewed_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def insert_failure_case(self, case: FailureCase) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_failure_cases"
                    "(failure_case_id,candidate_id,criterion_id,affected_turn,frozen_checkpoint,"
                    "status,regression_case_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        case.failure_case_id,
                        case.candidate_id,
                        case.criterion_id,
                        case.affected_turn,
                        _json_dumps(case.frozen_checkpoint),
                        case.status,
                        case.regression_case_id,
                        case.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_failure_case(self, failure_case_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM cert_failure_cases WHERE failure_case_id=?",
                    (failure_case_id,),
                ).fetchone()
                if row is None:
                    return None
                d = dict(row)
                d["frozen_checkpoint"] = json.loads(d["frozen_checkpoint"])
                return d
            finally:
                conn.close()

    def list_failure_cases(self, candidate_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._conn()
            try:
                if candidate_id is None:
                    rows = conn.execute("SELECT * FROM cert_failure_cases").fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM cert_failure_cases WHERE candidate_id=?", (candidate_id,)
                    ).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["frozen_checkpoint"] = json.loads(d["frozen_checkpoint"])
                    out.append(d)
                return out
            finally:
                conn.close()

    def mark_failure_resolved(self, failure_case_id: str) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE cert_failure_cases SET status='resolved' WHERE failure_case_id=?",
                    (failure_case_id,),
                )
                conn.commit()
            finally:
                conn.close()

    # ── Regression Cases ────────────────────────────────────────────────────

    def put_regression_case(self, case: RegressionCase) -> None:
        """Upsert a regression case, refusing to **weaken** an existing one.

        Regression cases are acceptance machinery: the Engineering Agent must
        never remove an active case or downgrade a CRITICAL/MAJOR case. This
        store-level guard makes the "do not weaken the test" rule structural.
        """
        with self._lock:
            conn = self._conn()
            try:
                existing = conn.execute(
                    "SELECT severity, active FROM cert_regression_cases WHERE regression_case_id=?",
                    (case.regression_case_id,),
                ).fetchone()
                _rank = {"CRITICAL": 0, "MAJOR": 1, "MINOR": 2}
                if existing is not None:
                    old_active = int(existing["active"])
                    new_active = 1 if case.active else 0
                    if old_active == 1 and new_active == 0:
                        raise CertificationStoreError(
                            f"Refusing to deactivate active regression case {case.regression_case_id}"
                        )
                    if _rank[case.severity.value] > _rank[existing["severity"]]:
                        raise CertificationStoreError(
                            f"Refusing to downgrade severity of regression case {case.regression_case_id}"
                        )
                conn.execute(
                    "INSERT OR REPLACE INTO cert_regression_cases"
                    "(regression_case_id,description,severity,checker,data,active,created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        case.regression_case_id,
                        case.description,
                        case.severity.value,
                        case.checker,
                        _json_dumps(case.data),
                        1 if case.active else 0,
                        case.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_regression_cases(self, active_only: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._conn()
            try:
                if active_only:
                    rows = conn.execute(
                        "SELECT * FROM cert_regression_cases WHERE active=1 ORDER BY "
                        "CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'MAJOR' THEN 1 ELSE 2 END"
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM cert_regression_cases").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d["data"] = json.loads(d["data"])
                    out.append(d)
                return out
            finally:
                conn.close()

    # ── Control-plane transition audit ──────────────────────────────────────

    def append_transition(self, transition: TransitionLog) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO cert_transitions"
                    "(transition_id,episode_id,from_state,to_state,reason,created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        transition.transition_id,
                        transition.episode_id,
                        transition.from_state.value,
                        transition.to_state.value,
                        transition.reason,
                        transition.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_transitions(self, episode_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM cert_transitions WHERE episode_id=? ORDER BY created_at",
                    (episode_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()


__all__ = ["CertificationStore", "CertificationStoreError", "content_digest"]
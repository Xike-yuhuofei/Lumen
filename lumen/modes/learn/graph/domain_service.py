"""Authoritative Learner-Domain writes for the Teaching Session Graph Candidate.

This is the ONLY place the candidate touches the Learner Domain.  Every write is
an atomic, idempotent :class:`DomainCommitRequest` — the candidate never bypasses
CAS / idempotency / provenance / reconciliation, and it threads the
``decision_id`` lineage into every evidence row it commits.

The candidate reuses the existing deterministic learners (grading, scheduler,
mastery policy) to *build* the proposed aggregate, then hands it to the Domain
Commit Foundation, which recomputes the reducible derived state from the evidence
ledger.  Nothing here re-implements the Agent Runtime or the LLM.
"""

from __future__ import annotations

import time
from typing import Any

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.assessment.grading import classify_error, grade_answer
from lumen.modes.learn.commit.commit_service import DomainCommitService
from lumen.modes.learn.commit.contract import (
    DomainCommitRequest,
    Evidence,
    OutboxIntent,
)
from lumen.modes.learn.commit.identity import new_uuid4
from lumen.modes.learn.domain.models import (
    ErrorRecord,
    ErrorType,
    QuizAttempt,
    RetryAttempt,
)
from lumen.modes.learn.policy.mastery import compute_mastery
from lumen.modes.learn.policy.policy import QUALITATIVE_TYPES

__all__ = ["TeachingGraphDomain"]


class TeachingGraphDomain:
    """Commit-backed Learner-Domain service used only by the candidate graph."""

    def __init__(self, store: LearningStore | None = None) -> None:
        self._store = store or LearningStore()

    @property
    def store(self) -> LearningStore:
        return self._store

    def current_version(self, path_id: str) -> int:
        return self._store.current_version(path_id)

    def snapshot(self, path_id: str):
        """Fresh, authoritative learner aggregate + version (never stale)."""
        return self._store.load(path_id), self._store.current_version(path_id)

    def read_decision_payload(self, decision_id: str) -> dict[str, Any] | None:
        """Return the immutable committed decision verbatim, or ``None``.

        Decision Replay seam: this is a pure read of the authoritative
        ``policy_decisions`` ledger — the policy is never re-run, and nothing
        here writes to the learner authority.
        """
        import json as _json

        row = self._store._repo.get_policy_decision(decision_id)
        if row is None or not row["decision_json"]:
            return None
        payload = _json.loads(row["decision_json"])
        return payload if isinstance(payload, dict) else None

    def match_misconception(self, progress, kp_id: str, statement: str) -> str:
        """Match a learner's wrong answer against the misconceptions registered
        on *kp_id* and return the deterministic misconception node id
        (``{kp_id}__mis{i}``), or ``""`` when nothing matches.

        The graph never receives a node id from the learner — it observes the
        belief (the wrong answer text) and the server decides which registered
        misconception (if any) that is. This is the diagnosis seam that makes
        the engine's ``remediate_misconception`` path reachable.
        """
        from difflib import SequenceMatcher

        text = " ".join(str(statement or "").strip().lower().split())
        if not text or not kp_id:
            return ""
        registered: list[tuple[str, str]] = []
        for module in progress.modules:
            for kp in module.knowledge_points:
                if kp.id == kp_id:
                    registered = [
                        (" ".join(m.statement.lower().split()), m.statement)
                        for m in kp.misconceptions
                    ]
        if not registered:
            return ""
        best_index, best_score = -1, 0.0
        for i, (normalized, _original) in enumerate(registered):
            score = SequenceMatcher(None, text, normalized).ratio()
            if normalized in text or text in normalized:
                score = max(score, 0.9)
            if score > best_score:
                best_index, best_score = i, score
        if best_index < 0 or best_score < 0.55:
            return ""
        return f"{kp_id}__mis{best_index}"

    def _track_error_records(self, progress, attempt) -> None:
        """Maintain ``progress.error_records`` from a graded ``QuizAttempt``.

        Mirrors the production post-answer pipeline: one error record per
        knowledge point carries the full retry history, a matched
        ``misconception_node_id`` rides along so the engine can remediate it,
        and any independent later correct answer graduates the record (this is
        what un-blocks the engine's remediation gate after a re-verification).
        """
        if not attempt.is_correct:
            existing = next(
                (
                    rec
                    for rec in progress.error_records
                    if rec.knowledge_point_id == attempt.knowledge_point_id
                ),
                None,
            )
            if existing is not None:
                existing.retry_history.append(
                    RetryAttempt(
                        timestamp=time.time(),
                        is_correct=False,
                        attempt_number=len(existing.retry_history) + 1,
                    )
                )
                existing.status = "retrying"
                if attempt.misconception_node_id:
                    existing.misconception_node_id = attempt.misconception_node_id
            else:
                progress.error_records.append(
                    ErrorRecord(
                        id=new_uuid4(),
                        question_id=attempt.question_id,
                        knowledge_point_id=attempt.knowledge_point_id,
                        module_id=attempt.module_id,
                        error_type=attempt.error_type or ErrorType.APPLICATION_ERROR,
                        self_attribution=attempt.self_attribution,
                        misconception_node_id=attempt.misconception_node_id,
                        status="active",
                    )
                )
        elif attempt.is_correct:
            for rec in progress.error_records:
                if rec.knowledge_point_id == attempt.knowledge_point_id and rec.status in (
                    "active",
                    "retrying",
                ):
                    rec.retry_history.append(
                        RetryAttempt(
                            timestamp=time.time(),
                            is_correct=True,
                            attempt_number=len(rec.retry_history) + 1,
                        )
                    )
                    rec.status = "graduated"

    # ── single authoritative commit ──────────────────────────────────────

    def _commit(
        self,
        progress,
        *,
        evidence: list[Evidence],
        decision_payload: dict[str, Any] | None,
        decision_id: str,
        action_id: str,
        outbox: list[OutboxIntent] | None = None,
    ):
        expected = self._store.current_version(progress.book_id)
        request = DomainCommitRequest(
            learner_id=progress.book_id,
            action_id=action_id,
            expected_learner_version=expected,
            proposed_state=progress.model_dump(mode="json"),
            evidence=evidence,
            decision=decision_payload,
            decision_id=decision_id,
            outbox=list(outbox or []),
        )
        return DomainCommitService(self._store._repo).commit(request)

    # ── pose: set the pending question under a decision ─────────────────

    def commit_pose(self, progress, pending, *, decision_payload: dict[str, Any], decision_id: str):
        """Persist the posed question; commits the assess decision + pending state.

        ``action_id`` is stable (derived from the decision) so a crash between
        pose and answer replays as one effect, never two.
        """
        progress.pending_question = pending
        pending.decision_payload = dict(decision_payload or {})
        progress.updated_at = time.time()
        return self._commit(
            progress,
            evidence=[],
            decision_payload=decision_payload,
            decision_id=decision_id,
            action_id=f"{decision_id}:pose",
        )

    # ── grade: append evidence + update state under the pose decision ────

    def commit_grade(
        self,
        progress,
        *,
        pending,
        user_answer: str,
        choice_options: dict[str, str],
        expected_answer: str,
        answer_for_grading: str,
        misconception_node_id: str,
        scheduler,
        question_bank: dict | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> bool:
        """Grade one answer, fold it through the post-answer pipeline, commit.

        The evidence carries ``decision_id``/``action_id`` from the pending
        question (the decision that *posed* it).  ``action_id`` is the attempt
        id (``{decision_id}:graded``), distinct from the pose id, so both phases
        are independently idempotent.
        """
        decision_id = getattr(pending, "decision_id", "") or ""
        pose_payload = getattr(pending, "decision_payload", None) or None
        is_correct = bool(expected_answer) and grade_answer(
            answer_for_grading, expected_answer, pending.question_type
        )

        # Build the proposed aggregate with the existing post-answer pipeline.
        attempt = QuizAttempt(
            question_id=pending.question_id,
            knowledge_point_id=pending.knowledge_point_id,
            module_id=pending.module_id,
            is_correct=is_correct,
            user_answer=user_answer,
            self_attribution="",
            error_type=None if is_correct else classify_error(user_answer),
            misconception_node_id="" if is_correct else misconception_node_id,
            question_kind=pending.question_kind,
        )
        progress.quiz_attempts.append(attempt)
        self._track_error_records(progress, attempt)
        kp_id = pending.knowledge_point_id
        if kp_id:
            progress.mastery_levels[kp_id] = compute_mastery(
                [a.is_correct for a in progress.quiz_attempts if a.knowledge_point_id == kp_id]
            )
            kp_type = progress.knowledge_types.get(kp_id)
            if kp_type is not None and kp_type in QUALITATIVE_TYPES and not is_correct:
                progress.qualitative_mastery[kp_id] = False
                progress.mastery_levels[kp_id] = min(
                    progress.mastery_levels.get(kp_id, 0.0), 0.4
                )
            if kp_type is not None and scheduler is not None:
                state = progress.repetition_states.get(
                    kp_id
                ) or scheduler.get_initial_state(kp_type)
                progress.repetition_states[kp_id] = state
                scheduler.schedule_next(state, kp_type, is_correct)
                progress.review_queue = scheduler.build_review_queue(progress)
        error_type = None if is_correct else classify_error(user_answer).value
        evidence = [
            Evidence(
                target_type="knowledge_point",
                target_id=kp_id,
                evidence_type="quiz_answer",
                outcome=is_correct,
                outcome_json={
                    "is_correct": is_correct,
                    "question_id": pending.question_id,
                    "module_id": pending.module_id,
                    "question_kind": pending.question_kind,
                    "error_type": error_type,
                    "self_attribution": "",
                    "misconception_node_id": misconception_node_id,
                },
                raw_response_json={"user_answer": user_answer},
                evaluator_kind="deterministic",
                evaluator_version="graph-candidate:v1",
                observed_at_ms=int(time.time() * 1000),
                session_id=session_id,
                turn_id=turn_id,
                decision_id=decision_id,
            )
        ]
        # Clear the pending question (it has been answered).
        progress.pending_question = None
        progress.updated_at = time.time()
        outbox = [OutboxIntent(payload=question_bank)] if question_bank else []
        self._commit(
            progress,
            evidence=evidence,
            decision_payload=pose_payload,  # same decision as the pose, idempotent
            decision_id=decision_id,
            action_id=f"{decision_id}:graded" if decision_id else new_uuid4(),
            outbox=outbox,
        )
        return is_correct

    # ── qualitative gate (CONCEPT / DESIGN) ──────────────────────────────

    def commit_qualitative(
        self,
        progress,
        *,
        kp_id: str,
        passed: bool,
        evidence_text: str,
        scheduler,
        misconception_node_id: str = "",
        decision_id: str = "",
        decision_payload: dict | None = None,
        session_id: str = "",
        turn_id: str = "",
    ):
        """Record a qualitative (CONCEPT / DESIGN) gate outcome as feynman
        evidence.

        The ``feynman_explanation`` evidence drives the qualitative mastery
        gate through the Domain Commit reducer (its ``outcome`` is the
        evaluator's pass/fail judgement), and a failed check that matched a
        registered misconception is recorded as an active error record so the
        engine can remediate it. A pass graduates any open error record for
        the objective (the learner has just re-articulated the idea
        correctly), un-blocking remediation.
        """
        progress.qualitative_mastery[kp_id] = bool(passed)
        current = progress.mastery_levels.get(kp_id, 0.0)
        progress.mastery_levels[kp_id] = max(current, 1.0) if passed else min(current, 0.4)
        if evidence_text:
            progress.feynman_explanations[kp_id] = evidence_text
        module_id = next(
            (
                mod.id
                for mod in progress.modules
                if any(kp.id == kp_id for kp in mod.knowledge_points)
            ),
            "",
        )
        error_type = None if passed else ErrorType.APPLICATION_ERROR
        attempt = QuizAttempt(
            question_id=f"feynman:{kp_id}",
            knowledge_point_id=kp_id,
            module_id=module_id,
            is_correct=bool(passed),
            user_answer=evidence_text or "",
            error_type=error_type,
            question_kind="application",
            misconception_node_id="" if passed else misconception_node_id,
        )
        progress.quiz_attempts.append(attempt)
        self._track_error_records(progress, attempt)
        # The check has been answered and graded — clear the pending question
        # so the same decision is never re-graded (idempotent by action_id).
        progress.pending_question = None
        if passed and scheduler is not None:
            kp_type = progress.knowledge_types.get(kp_id)
            if kp_type is not None:
                state = progress.repetition_states.get(kp_id) or scheduler.get_initial_state(
                    kp_type
                )
                progress.repetition_states[kp_id] = state
                scheduler.schedule_next(state, kp_type, is_correct=True)
                progress.review_queue = scheduler.build_review_queue(progress)
        progress.updated_at = time.time()
        evidence = [
            Evidence(
                target_type="knowledge_point",
                target_id=kp_id,
                evidence_type="feynman_explanation",
                outcome=bool(passed),
                outcome_json={
                    "passed": bool(passed),
                    "question_id": f"feynman:{kp_id}",
                    "module_id": module_id,
                    "question_kind": "application",
                    "error_type": error_type.value if error_type else None,
                    "misconception_node_id": "" if passed else misconception_node_id,
                },
                raw_response_json={"user_answer": evidence_text or ""},
                evaluator_kind="llm",
                evaluator_version="graph-candidate:feynman:v1",
                observed_at_ms=int(time.time() * 1000),
                session_id=session_id,
                turn_id=turn_id,
                decision_id=decision_id,
            )
        ]
        self._commit(
            progress,
            evidence=evidence,
            decision_payload=decision_payload,
            decision_id=decision_id,
            action_id=f"{decision_id}:graded" if decision_id else new_uuid4(),
        )
        return bool(passed)
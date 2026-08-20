"""Certification Controller — the Phase 1 Teaching Optimization Loop driver.

Canonical home: ``lumen/cert``.

Implements the **frozen Certification State Machine** over the real planes:

    EPISODE_INIT → TURN_GENERATION → TURN_EVALUATION
      ├─ evaluator INVALID → recovery/retry (never a tutor NO-GO) → over budget ⇒ BLOCKED
      ├─ all VALID GO       → FinalTurnStatus = PASS → next turn (or EPISODE_PASS at turn 10)
      └─ any VALID NO-GO    → FAILURE_REVIEW → FAILURE_ATTRIBUTION
            LUMEN     → freeze failure → Engineering mutation → Frozen Replay
                        → Minimal Regression → restart Episode from Turn 1 (new candidate)
            EVALUATOR/RUBRIC/SIMULATOR/INFRA → harness/component fix; never mutate Lumen
            UNCERTAIN → BLOCKED (fail closed)

Termination Safety: every autonomous loop carries a finite budget
(evaluator retry, patch attempts, total mutations). Reaching a budget ⇒ BLOCKED.
``FAIL`` means confirmed evidence the candidate did not satisfy requirements;
``BLOCKED`` means no valid certification conclusion can be formed.

Raw verdict and Final Turn Status stay strictly separated:
only a *confirmed LUMEN* failure produces Final FAIL; UNCERTAIN ⇒ UNRESOLVED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Callable
import uuid

from .attribution import FailureReviewer
from .engineering import EngineeringAgent, UnpatchableFailure
from .evaluators import build_evaluator_suite
from .llm import ModelGateway
from .models import (
    Attribution,
    CandidateManifest,
    ContextManifest,
    Episode,
    EpisodeEnd,
    EvaluationStatus,
    FailureCase,
    FinalTurnStatus,
    Phase1State,
    RawVerdict,
    TransitionLog,
    TurnArtifact,
    content_digest,
)
from .planes import EvaluationPlane, TeachingPlane
from .regression import RegressionRunner, ReplayRunner
from .simulator import LearnerSimulator
from .store import CertificationStore
from .tutor import LumenTutor

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Budget:
    """Finite budgets for every autonomous loop."""

    max_turns: int = 10
    evaluator_attempts_per_turn: int = 3  # 1 + retries
    patch_budget: int = 3  # max engineering mutations per certification attempt
    replay_attempts_per_failure: int = 3


#: Context digests pin trajectory (drives restart) vs evaluation (drives
#: re-adjudication) so the system can enforce the certification-context rules.
def build_contexts(
    *,
    scenario: dict[str, Any],
    evaluation_config: dict[str, Any],
) -> ContextManifest:
    return ContextManifest(
        trajectory_context_id=f"traj-{content_digest(scenario)[:24]}",
        evaluation_context_id=f"eval-{content_digest(evaluation_config)[:24]}",
        trajectory_digest=content_digest(scenario),
        evaluation_digest=content_digest(evaluation_config),
    )


@dataclass(slots=True)
class CertificationOutcome:
    status: EpisodeEnd  # PASS / FAIL / BLOCKED
    episode_id: str
    candidate_id: str
    trajectory_context_id: str
    evaluation_context_id: str
    final_turn_statuses: list[str] = field(default_factory=list)
    patches_applied: int = 0
    blocked_reason: str = ""
    message: str = ""


class CertificationController:
    """Control plane — decides continue / stop / retry / patch / restart / certify.

    Holds **no** Tutor mutation permission itself: mutation is always delegated
    through the Attribution Gate to the Engineering Agent, and only on a
    confirmed LUMEN failure.
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        store: CertificationStore,
        candidate: CandidateManifest,
        contexts: ContextManifest,
        scenario: dict[str, Any],
        language: str = "en",
        budget: Budget | None = None,
        harness_fix: Callable[[str, Any], None] | None = None,
        perspective_ids: list[str] | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._candidate = candidate
        self._contexts = contexts
        self._scenario = dict(scenario)
        self._language = language
        self._budget = budget or Budget()
        self._perspective_ids = perspective_ids
        # Component-fix hook receives (attribution, reason); a provider may
        # repair the evaluator/rubric/simulator and clear the flag. Default None
        # means non-LUMEN attribution terminates the attempt (BLOCKED).
        self._harness_fix = harness_fix
        self._patches_applied = 0
        self._last_certified_episode: str | None = None

    def _evaluator_suite(self, gateway):
        return build_evaluator_suite(gateway, perspective_ids=self._perspective_ids)

    def _store_candidate(self, candidate: CandidateManifest) -> None:
        self._store.put_candidate(candidate)

    async def _run_partial_episode(
        self,
        *,
        episode_id: str,
        candidate: CandidateManifest,
        start_turn: int,
        history_prior: list[dict[str, Any]],
        first_learner_utterance: str,
    ) -> dict[str, Any]:
        """Run turns starting at ``start_turn`` under one candidate.

        Returns a partial outcome dict used by the machine. Does NOT exceed
        ``max_turns`` total (assumes prior turns already recorded when restarting).
        """
        ep = Episode(
            episode_id=episode_id,
            candidate_id=candidate.effective_candidate_id,
            trajectory_context_id=self._contexts.trajectory_context_id,
            evaluation_context_id=self._contexts.evaluation_context_id,
        )
        self._store.create_episode(ep)
        self._transition(episode_id, Phase1State.EPISODE_INIT, Phase1State.TURN_GENERATION, "episode init")

        plane = TeachingPlane(
            tutor=LumenTutor(self._gateway, candidate=candidate, language=self._language),
            simulator=LearnerSimulator(self._gateway, candidate=candidate),
        )
        eval_plane = EvaluationPlane(self._evaluator_suite(self._gateway))
        reviewer = FailureReviewer(self._gateway)

        history = [dict(m) for m in history_prior]
        learner_utterance = first_learner_utterance
        final_statuses: list[str] = []
        turn = start_turn

        while turn <= self._budget.max_turns:
            self._transition(episode_id, Phase1State.TURN_GENERATION, Phase1State.TURN_GENERATION, f"turn {turn} teach")
            # Generate Lumen teaching action for the current learner utterance.
            tutor_action = await plane.teach(
                turn_index=turn, history=history, learner_utterance=learner_utterance
            )
            # Simulator produces the NEXT learner reply (hidden state diagnostic only).
            sim = await plane.respond_like_learner(
                turn_index=turn, history=history, tutor_action=tutor_action
            )

            turn_artifact = TurnArtifact(
                episode_id=episode_id,
                turn_index=turn,
                learner_utterance=learner_utterance,
                tutor_action=tutor_action,
                prior_conversation=[dict(m) for m in history],
                hidden_learner_state=sim["hidden"],
            )
            self._store.append_turn(turn_artifact)

            public_history = [dict(m) for m in history]
            history.append({"role": "user", "content": learner_utterance})
            history.append({"role": "assistant", "content": tutor_action})
            next_learner_utterance = str(sim["utterance"])

            # ── Evaluate the immutable trace for this turn ────────────────
            self._transition(episode_id, Phase1State.TURN_GENERATION, Phase1State.TURN_EVALUATION, f"turn {turn} evaluate")
            evaluations, blocked_invalid = await self._evaluate_turn(
                episode_id=episode_id,
                turn_index=turn,
                learner_utterance=learner_utterance,
                tutor_action=tutor_action,
                prior=public_history,
                eval_plane=eval_plane,
            )
            for r in evaluations:
                self._store.append_evaluation(r)

            if blocked_invalid:
                self._store.finish_episode(episode_id, EpisodeEnd.BLOCKED, turn)
                self._transition(episode_id, Phase1State.TURN_EVALUATION, Phase1State.BLOCKED, "evaluator INVALID exceeded")
                return {"final_statuses": final_statuses, "blocked": "evaluator INVALID exceeded retry budget", "turn": turn}

            non_go = [r for r in evaluations if r.decision == RawVerdict.NO_GO]
            if not non_go:
                # All valid GO -> PASS (raw verdicts), never a tutor-level FAIL.
                self._store.set_turn_final_status(episode_id, turn, FinalTurnStatus.PASS.value)
                final_statuses.append(FinalTurnStatus.PASS.value)
                self._store.finish_episode(episode_id, EpisodeEnd.NOT_DONE, turn)
                turn += 1
                learner_utterance = next_learner_utterance
                continue

            # ── Any raw NO-GO only triggers Review; only a confirmed LUMEN
            #    failure becomes a Final FAIL. ─────────────────────────────
            self._transition(episode_id, Phase1State.TURN_EVALUATION, Phase1State.FAILURE_REVIEW, f"turn {turn} NO_GO")
            review = await reviewer.review(
                episode_id=episode_id,
                turn_index=turn,
                results=evaluations,
                tutor_action=tutor_action,
                learner_utterance=learner_utterance,
                prior=public_history,
                hidden_learner_state=sim["hidden"],
            )
            self._store.append_failure_review(review)
            self._transition(episode_id, Phase1State.FAILURE_REVIEW, Phase1State.FAILURE_ATTRIBUTION, f"attribution {review.attribution.value}")

            handled = await self._handle_attribution(
                episode_id=episode_id,
                turn=turn,
                candidate=candidate,
                review=review,
                learner_utterance=learner_utterance,
                tutor_action=tutor_action,
                prior=public_history,
                failing_evaluator_ids=[r.evaluator_id for r in evaluations if r.decision == RawVerdict.NO_GO],
            )
            return {"final_statuses": final_statuses, "handled": handled, "turn": turn}

        # loop ended because turn > max_turns
        return {"final_statuses": final_statuses, "done": True, "turn": turn}

    async def _evaluate_turn(self, *, episode_id, turn_index, learner_utterance, tutor_action, prior, eval_plane):
        """Evaluators with INVALID recovery/retry; never produces a tutor NO-GO."""
        attempts = max(1, self._budget.evaluator_attempts_per_turn)
        last_results: list[Any] = []
        for _ in range(attempts):
            last_results = await eval_plane.evaluate_turn(
                episode_id=episode_id,
                turn_index=turn_index,
                learner_utterance=learner_utterance,
                tutor_action=tutor_action,
                prior=prior,
            )
            if all(r.evaluation_status == EvaluationStatus.VALID for r in last_results):
                # TEMP: we already persisted in caller; but retry loop may re-run.
                return last_results, False
        # exhausted retries with at least one INVALID -> BLOCKED (no tutor NO-GO).
        return last_results, True

    async def _handle_attribution(self, *, episode_id, turn, candidate, review, learner_utterance, tutor_action, prior, failing_evaluator_ids):
        attribution = review.attribution
        if attribution == Attribution.LUMEN:
            self._patches_applied += 1
            if self._patches_applied > self._budget.patch_budget:
                self._transition(episode_id, Phase1State.FAILURE_ATTRIBUTION, Phase1State.BLOCKED, "patch budget exceeded")
                return {"result": "BLOCKED", "reason": "patch_budget_exceeded"}
            # → Freeze the failure (immutable, replayable).
            failing_eval_id = failing_evaluator_ids[0] if failing_evaluator_ids else "context"
            case = FailureCase(
                failure_case_id=f"{episode_id}:t{turn}:case",
                candidate_id=candidate.effective_candidate_id,
                criterion_id=review.attribution.value + ":lumen",
                affected_turn=turn,
                frozen_checkpoint={
                    "prior_conversation": prior,
                    "learner_utterance": learner_utterance,
                    "turn_index": turn,
                    "failing_evaluator_id": failing_eval_id,
                    "tutor_action_at_failure": tutor_action,
                },
                status="frozen",
            )
            self._store.insert_failure_case(case)

            # → Engineering mutation (permission confirmed LUMEN).
            self._transition(episode_id, Phase1State.FAILURE_ATTRIBUTION, Phase1State.PATCHING, "LUMEN -> engineering")
            new_candidate: CandidateManifest | None = None
            try:
                new_candidate = await EngineeringAgent(self._gateway).place_patch(
                    review=review, base_candidate=candidate
                )
            except UnpatchableFailure as exc:
                self._transition(episode_id, Phase1State.PATCHING, Phase1State.BLOCKED, f"unpatchable {exc}")
                return {"result": "BLOCKED", "reason": f"unpatchable: {exc}"}
            self._store_candidate(new_candidate)

            # → Frozen Replay (same confirmed failure must be fixed).
            self._transition(episode_id, Phase1State.PATCHING, Phase1State.FROZEN_REPLAY, "frozen replay")
            replay = await ReplayRunner(
                self._gateway, lambda: self._evaluator_suite(self._gateway)
            ).replay(
                candidate=new_candidate,
                frozen_checkpoint=case.frozen_checkpoint,
                failing_evaluator_id=failing_eval_id,
                language=self._language,
            )
            if not replay["passed"]:
                self._transition(episode_id, Phase1State.FROZEN_REPLAY, Phase1State.FAILURE_REVIEW, "frozen replay not fixed")
                return {"result": "REPLAY_NOT_FIXED", "reason": replay["evidence"], "new_candidate": new_candidate}

            # → Minimal Regression.
            self._transition(episode_id, Phase1State.FROZEN_REPLAY, Phase1State.REGRESSION, "minimal regression")
            regression = await RegressionRunner(
                self._gateway, self._store, lambda: self._evaluator_suite(self._gateway)
            ).run_full(new_candidate, language=self._language, data={"episode_id": episode_id})
            failed = [r for r in regression if not r.passed and r.severity.value == "CRITICAL"]
            if failed:
                return {"result": "REGRESSION_FAILED", "reason": "; ".join(f"{r.case_id}:{r.evidence}" for r in failed), "new_candidate": new_candidate}

            # → New EffectiveCandidate: restart certification from Turn 1.
            self._transition(episode_id, Phase1State.REGRESSION, Phase1State.EPISODE_INIT, "restart turn 1 with new candidate")
            return {"result": "RESTART", "new_candidate": new_candidate}

        if attribution == Attribution.UNCERTAIN:
            self._transition(episode_id, Phase1State.FAILURE_ATTRIBUTION, Phase1State.BLOCKED, "UNCERTAIN fail closed")
            return {"result": "BLOCKED", "reason": "UNCERTAIN fail closed"}

        # EVALUATOR / RUBRIC / SIMULATOR / INFRA -> harness/component fix, never mutate Lumen.
        self._transition(episode_id, Phase1State.FAILURE_ATTRIBUTION, Phase1State.BLOCKED, f"harness fix {attribution.value}")
        if self._harness_fix is not None:
            self._harness_fix(attribution.value, review.reasoning)
            return {"result": "HARNESS_FIX_REQUESTED", "reason": attribution.value}
        return {
            "result": "BLOCKED",
            "reason": f"non-LUMEN attribution {attribution.value} without harness-fix provider (Lumen not mutated)",
        }

    def _new_episode_id(self) -> str:
        return f"ep-{uuid.uuid4().hex[:20]}"

    def _transition(self, episode_id: str, from_state: Phase1State, to_state: Phase1State, reason: str) -> None:
        if from_state == Phase1State.EPISODE_INIT and to_state == Phase1State.EPISODE_INIT:
            return
        self._store.append_transition(
            TransitionLog(
                transition_id=f"{episode_id}:{uuid.uuid4().hex[:8]}",
                episode_id=episode_id,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
            )
        )

    async def certify(self) -> CertificationOutcome:
        """Drive one certification attempt to a PASS / FAIL / BLOCKED conclusion."""
        self._store_candidate(self._candidate)
        self._store.put_context(self._contexts)

        current_candidate = self._candidate
        start_turn = 1
        prior_history: list[dict[str, Any]] = []
        opening = f"I want to learn {self._scenario['subject']}."
        final_statuses: list[str] = []

        safety = 0
        # patch_budget bounds the number of candidate mutations for this attempt.
        while safety <= self._budget.patch_budget + 2:
            safety += 1
            episode_id = self._new_episode_id()
            try:
                partial = await self._run_partial_episode(
                    episode_id=episode_id,
                    candidate=current_candidate,
                    start_turn=start_turn,
                    history_prior=prior_history,
                    first_learner_utterance=opening,
                )
            except Exception as exc:  # noqa: BLE001
                # Infra/LLM exception anywhere in the plane -> fail closed to
                # BLOCKED (no unauthorised Lumen mutation, no false FAIL).
                logger.error("certification episode %s raised: %s", episode_id, exc, exc_info=True)
                return CertificationOutcome(
                    status=EpisodeEnd.BLOCKED,
                    episode_id=episode_id,
                    candidate_id=current_candidate.effective_candidate_id,
                    trajectory_context_id=self._contexts.trajectory_context_id,
                    evaluation_context_id=self._contexts.evaluation_context_id,
                    final_turn_statuses=list(final_statuses),
                    patches_applied=self._patches_applied,
                    blocked_reason=f"infra/LLM exception: {exc}",
                )
            final_statuses = partial.get("final_statuses", final_statuses)

            handled = partial.get("handled")
            if partial.get("blocked"):
                outcome = CertificationOutcome(
                    status=EpisodeEnd.BLOCKED,
                    episode_id=episode_id,
                    candidate_id=current_candidate.effective_candidate_id,
                    trajectory_context_id=self._contexts.trajectory_context_id,
                    evaluation_context_id=self._contexts.evaluation_context_id,
                    final_turn_statuses=final_statuses,
                    patches_applied=self._patches_applied,
                    blocked_reason=partial["blocked"],
                )
                outcome.message = "evaluator INVALID exhausted retry budget; BLOCKED"
                return outcome

            if handled is None:
                # All turns PASSed -> certify.
                if len(final_statuses) >= self._budget.max_turns:
                    self._store.finish_episode(episode_id, EpisodeEnd.PASS, len(final_statuses))
                    self._last_certified_episode = episode_id
                    return CertificationOutcome(
                        status=EpisodeEnd.PASS,
                        episode_id=episode_id,
                        candidate_id=current_candidate.effective_candidate_id,
                        trajectory_context_id=self._contexts.trajectory_context_id,
                        evaluation_context_id=self._contexts.evaluation_context_id,
                        final_turn_statuses=list(final_statuses),
                        patches_applied=self._patches_applied,
                        message="10-Turn Long-Horizon Teaching Stability Episode PASS",
                    )
                # not enough turns and not blocked -> safety guard (shouldn't happen)
                return CertificationOutcome(
                    status=EpisodeEnd.BLOCKED,
                    episode_id=episode_id,
                    candidate_id=current_candidate.effective_candidate_id,
                    trajectory_context_id=self._contexts.trajectory_context_id,
                    evaluation_context_id=self._contexts.evaluation_context_id,
                    final_turn_statuses=list(final_statuses),
                    blocked_reason="turn loop ended early without PASS/BLOCKED",
                )

            result = handled["result"]
            reason = handled.get("reason", handled.get("result", ""))

            if result == "RESTART":
                current_candidate = handled["new_candidate"]
                start_turn = 1
                prior_history = []
                opening = f"I want to learn {self._scenario['subject']}."
                final_statuses = []
                continue  # restart Episode from Turn 1 with new candidate

            if result == "REPLAY_NOT_FIXED":
                # Same confirmed LUMEN criterion still failing -> allowed to keep
                # patching (bounded by patch_budget already incremented).
                current_candidate = handled["new_candidate"]
                start_turn = 1
                prior_history = []
                opening = f"I want to learn {self._scenario['subject']}."
                final_statuses = []
                continue

            if result == "REGRESSION_FAILED":
                # New failure signal found in regression -> must re-Review. In a
                # strictly automated mode without a reviewer loop, we fail closed.
                return CertificationOutcome(
                    status=EpisodeEnd.BLOCKED,
                    episode_id=episode_id,
                    candidate_id=current_candidate.effective_candidate_id,
                    trajectory_context_id=self._contexts.trajectory_context_id,
                    evaluation_context_id=self._contexts.evaluation_context_id,
                    final_turn_statuses=list(final_statuses),
                    patches_applied=self._patches_applied,
                    blocked_reason=f"regression failed: {reason}",
                )

            if result == "HARNESS_FIX_REQUESTED":
                return CertificationOutcome(
                    status=EpisodeEnd.BLOCKED,
                    episode_id=episode_id,
                    candidate_id=current_candidate.effective_candidate_id,
                    trajectory_context_id=self._contexts.trajectory_context_id,
                    evaluation_context_id=self._contexts.evaluation_context_id,
                    final_turn_statuses=list(final_statuses),
                    patches_applied=self._patches_applied,
                    blocked_reason=f"harness fix requested: {reason}",
                )

            # BLOCKED / default fallthrough
            return CertificationOutcome(
                status=EpisodeEnd.BLOCKED,
                episode_id=episode_id,
                candidate_id=current_candidate.effective_candidate_id,
                trajectory_context_id=self._contexts.trajectory_context_id,
                evaluation_context_id=self._contexts.evaluation_context_id,
                final_turn_statuses=list(final_statuses),
                patches_applied=self._patches_applied,
                blocked_reason=reason,
            )

        # safety loop exhausted (should not happen — budgets bound it)
        return CertificationOutcome(
            status=EpisodeEnd.BLOCKED,
            episode_id=self._last_certified_episode or "",
            candidate_id=self._candidate.effective_candidate_id,
            trajectory_context_id=self._contexts.trajectory_context_id,
            evaluation_context_id=self._contexts.evaluation_context_id,
            final_turn_statuses=list(final_statuses),
            patches_applied=self._patches_applied,
            blocked_reason="safety loop exhausted",
        )


__all__ = [
    "CertificationController",
    "CertificationOutcome",
    "Budget",
    "build_contexts",
]
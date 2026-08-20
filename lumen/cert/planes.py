"""Teaching / Evaluation / Control Plane isolation for Phase 1 certification.

Canonical home: ``lumen/cert``.

The Certification loop must keep three planes strictly isolated:

    Teaching Plane   Learner Simulator <-> Lumen Tutor  (dialogue only)
    Evaluation Plane Immutable Trace -> Evaluators -> Failure Review
    Control Plane    continue / stop / retry / patch / restart / certify

Enforced invariants (code, not convention):
* **Evaluation-plane output (raw verdicts, judge reasoning, failure review,
  diagnosis, regression results) never enters the Teaching plane.** The Tutor
  is constructed with only the candidate + scenario, and its messages come from
  conversation_history + the current learner utterance — never from evaluation.
* **Lumen never sees hidden learner state.** The Tutor receives only learner
  utterances; hidden_learner_state lives on the TurnArtifact for the Failure
  Reviewer.
* Roles are interfaces here; the Controller composes them and authorizes
  mutations only via the Attribution Gate.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TeachingPlane:
    """Owns the Learner-Simulator <-> Tutor dialogue.

    Isolation: the Tutor and Simulator only ever see the public conversation.
    Nothing from the Evaluation or Control plane is threaded in.

    A Turn = one Learner Utterance + the subsequent Lumen Teaching Action. The
    Simulator's reply after a tutor action becomes the *next* turn's learner
    utterance, so the episode forms one continuous trajectory.
    """

    def __init__(self, tutor: Any, simulator: Any) -> None:
        self._tutor = tutor
        self._simulator = simulator

    async def teach(
        self,
        *,
        turn_index: int,
        history: list[dict[str, Any]],
        learner_utterance: str,
    ) -> str:
        """Lumen produces one Teaching Action for the learner utterance."""
        return await self._tutor.run_turn(
            turn_index=turn_index,
            prior_conversation=history,
            learner_utterance=learner_utterance,
        )

    async def respond_like_learner(
        self,
        *,
        turn_index: int,
        history: list[dict[str, Any]],
        tutor_action: str,
    ) -> dict[str, Any]:
        """Simulated learner replies to the tutor action -> next utterance + hidden."""
        return await self._simulator.generate(
            tutor_action=tutor_action,
            prior=history,
            turn_index=turn_index,
        )


# ── Evaluation Plane ─────────────────────────────────────────────────────────


class EvaluationPlane:
    """Read-only evaluation over an immutable trace snapshot.

    Produces per-turn raw evaluation results; carries no Tutor mutation.
    """

    def __init__(self, evaluators: list[Any]) -> None:
        self._evaluators = evaluators

    async def evaluate_turn(
        self,
        *,
        episode_id: str,
        turn_index: int,
        learner_utterance: str,
        tutor_action: str,
        prior: list[dict[str, Any]],
    ) -> list[Any]:
        results = []
        for evaluator in self._evaluators:
            result = await evaluator.run(
                episode_id=episode_id,
                turn_index=turn_index,
                learner_utterance=learner_utterance,
                tutor_action=tutor_action,
                prior=prior,
            )
            results.append(result)
        return results


# ── Control Plane ────────────────────────────────────────────────────────────


class Controller(Protocol):
    """Control-plane interface: decides continue/stop/retry/patch/restart."""

    def transition(self, to: str, reason: str) -> None: ...


__all__ = ["TeachingPlane", "EvaluationPlane", "Controller"]
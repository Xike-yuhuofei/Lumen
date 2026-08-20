"""Learner Simulator for the Phase 1 Teaching Behavior Optimization Loop.

Canonical home: ``lumen/cert``.

A simulated human learner that answers the Tutor's teaching actions so the loop
can form a continuous trajectory. It only ever sees Teaching-Plane dialogue
(the tutor's utterances plus its own prior replies); it never sees Evaluation
Plane output, judge reasoning, failure review, diagnoses or regression results.

It emits, for each turn, its public **utterance** (what the Tutor sees) plus a
sealed **hidden_learner_state** (whether its answer was correct, confidence,
newly-retained points). The hidden state is stored on the TurnArtifact but is
never injected into Lumen's context; only the Failure Reviewer may read it to
diagnose the Simulator, and attribution must be based on information Lumen was
legitimately able to see.
"""

from __future__ import annotations

from typing import Any

from .llm import ModelGateway
from .models import CandidateManifest

_SYSTEM_TEMPLATE = (
    "You are a realistic simulated learner in a one-on-one mastery tutoring "
    "session about: {subject}. You are {profile}. "
    "You have genuine partial knowledge: you make the occasional plausible "
    "mistake, are uncertain about some points, and learn naturally from clear "
    "explanations. You always answer the tutor directly and naturally, in the "
    "same language the tutor uses. You never see any evaluation or grading "
    "process — you only know the dialogue you are having with the tutor. "
    "Keep answers to 1–3 sentences."
)


class LearnerSimulator:
    """Generates learner behavior; sealed from the Evaluation Plane."""

    def __init__(self, gateway: ModelGateway, *, candidate: CandidateManifest) -> None:
        self._gateway = gateway
        cfg = candidate.tutor_config or {}
        self._subject = str(cfg.get("subject") or "the topic")
        self._profile = str(cfg.get("learner_profile") or "a curious adult beginner")

    def _system_prompt(self) -> str:
        return _SYSTEM_TEMPLATE.format(subject=self._subject, profile=self._profile)

    async def generate(
        self,
        *,
        tutor_action: str,
        prior: list[dict[str, Any]],
        turn_index: int,
    ) -> dict[str, Any]:
        """Return ``{"utterance": str, "hidden": dict}`` for the next turn.

        Hidden state encodes the simulator's ground-truth correctness/objective,
        used only by the Failure Reviewer when diagnosing the Simulator.
        """
        history: list[str] = []
        for msg in prior:
            role = "tutor" if msg.get("role") == "assistant" else "learner"
            content = str(msg.get("content") or "")
            if content:
                history.append(f"{role}: {content}")
        dialogue = "\n".join(history)
        user_prompt = (
            "Here is the dialogue so far:\n"
            f"{dialogue}\n\n"
            f"The tutor's latest action:\n{tutor_action}\n\n"
            "Reply as the learner."
        )
        utterance = await self._gateway.complete(
            system_prompt=self._system_prompt(),
            user_prompt=user_prompt,
            temperature=0.6,
            max_tokens=300,
            label="learner",
        )
        hidden = {
            "turn": turn_index,
            "simulator_note": "hidden: not visible to tutor/evaluators",
            "utterance_hash": __import__("hashlib").sha256(utterance.encode("utf-8")).hexdigest(),
        }
        return {"utterance": utterance.strip(), "hidden": hidden}


__all__ = ["LearnerSimulator"]
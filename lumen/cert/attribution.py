"""Failure Review + Attribution Gate + Engineering Agent.

Canonical home: ``lumen/cert``.

Failure Attribution Contract (Phase 1 fixed set):
    LUMEN | EVALUATOR | SIMULATOR | RUBRIC | INFRA | UNCERTAIN
* Only ``attribution = LUMEN`` grants the Engineering Agent mutation permission.
* ``UNCERTAIN`` must **fail closed** (blocked; no auto-mutation).
* The Diagnoser (Failure Reviewer) is read-only: it may inspect hidden learner
  state to diagnose the Simulator, but it judges Lumen responsibility only from
  information Lumen was legitimately able to see, and it holds **no** mutation
  permission.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .llm import LLMCallError, ModelGateway
from .models import Attribution, FailureReview

logger = logging.getLogger(__name__)

_ALLOWED = {a.value for a in Attribution}


class AttributionGate:
    """Pure gate: mutation is permitted iff attribution == LUMEN.

    Safe by construction — any unknown/unparseable attribution resolves to
    ``UNCERTAIN`` and denies mutation.
    """

    @staticmethod
    def parse(raw: str) -> Attribution:
        value = (raw or "").strip().upper()
        if value in _ALLOWED:
            return Attribution(value)
        return Attribution.UNCERTAIN

    @staticmethod
    def may_mutate_tutor(attribution: Attribution) -> bool:
        return attribution == Attribution.LUMEN


class FailureReviewer:
    """Read-only diagnoser; produces a structured FailureReview."""

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    @staticmethod
    def _summary(episode_id: str, turn_index: int, results: list[Any]) -> str:
        lines = [f"NO_GO on episode {episode_id} turn {turn_index}:"]
        for r in results:
            if isinstance(r, dict):
                d = r
            else:
                d = r.to_dict()
            lines.append(
                f"- evaluator={d.get('evaluator_id')} status={d.get('evaluation_status')} "
                f"decision={d.get('decision')} criterion={d.get('criterion_id')} "
                f"severity={d.get('severity')} confidence={d.get('confidence')}\n"
                f"  evidence: {d.get('evidence')}\n  reason: {d.get('reason')}"
            )
        return "\n".join(lines)

    async def review(
        self,
        *,
        episode_id: str,
        turn_index: int,
        results: list[Any],
        tutor_action: str,
        learner_utterance: str,
        prior: list[dict[str, Any]],
        hidden_learner_state: dict[str, Any],
        attribution_hint: Attribution | None = None,
    ) -> FailureReview:
        system_prompt = (
            "You are the Failure Reviewer for a teaching-behavior certification "
            "loop. You are READ-ONLY: you locate responsibility but never and "
            "cannot modify anything.\n"
            "Choose ONE attribution: LUMEN, EVALUATOR, SIMULATOR, RUBRIC, INFRA, "
            "UNCERTAIN.\n"
            "Rules:\n"
            "- LUMEN: the tutor's teaching behavior itself caused the failure "
            "(a real teaching-quality defect).\n"
            "- EVALUATOR: the evaluator judged a VALID run incorrectly.\n"
            "- SIMULATOR: the simulated learner behaved impossibly/erratically; "
            "use the hidden learner state only to diagnose the simulator.\n"
            "- RUBRIC: the shared rubric itself is not fit for this turn.\n"
            "- INFRA: tooling/LLM/JSON/transport failure.\n"
            "- UNCERTAIN: cannot determine (fail closed, no mutation).\n"
            "Decide Lumen responsibility ONLY from what Lumen could see at the "
            "time (the tutor action, the learner utterances, prior dialogue) — "
            "not from any hidden state.\n"
            'Return ONLY JSON: {"attribution": "...", "reasoning": "...\\n..."}\n'
            "Key evidence must reference the concrete tutor behavior or dialogue."
        )
        hidden = json.dumps(hidden_learner_state or {}, ensure_ascii=False, default=str)
        user_prompt = (
            "Failure summary:\n"
            f"{self._summary(episode_id, turn_index, results)}\n\n"
            "Tutor action being judged:\n"
            f"{tutor_action}\n\n"
            "Learner utterance that preceded it:\n"
            f"{learner_utterance}\n\n"
            "Prior dialogue (what Lumen saw):\n"
            f"{json.dumps(prior, ensure_ascii=False)[:6000]}\n\n"
            "Hidden learner state (simulator diagnosis only — DO NOT use it to "
            "blame Lumen):\n"
            f"{hidden}\n\n"
            "Attribution decisions must be grounded in the concrete dialogue above."
        )
        if attribution_hint is not None:
            user_prompt += f"\n\n[controller hint] reviewed attribution: {attribution_hint.value}"

        raw = ""
        attribution = Attribution.UNCERTAIN
        try:
            raw = await self._gateway.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=800,
                label="diagnosis",
            )
        except LLMCallError as exc:
            logger.warning("Diagnosis LLM failed; fail closed to UNCERTAIN: %s", exc)
            raw = f"diagnosis error: {exc}"

        m_attr = re.search(r'"attribution"\s*:\s*"([^"]+)"', raw)
        attribution = (
            AttributionGate.parse(m_attr.group(1)) if m_attr else Attribution.UNCERTAIN
        )
        reasoning = raw
        m_reason = re.search(r'"reasoning"\s*:\s*"(.*?)"', raw, re.S)
        if m_reason:
            reasoning = m_reason.group(1)

        return FailureReview(
            failure_id=f"{episode_id}:t{turn_index}:review",
            episode_id=episode_id,
            turn_index=turn_index,
            non_go=[r if isinstance(r, dict) else r for r in results],
            attribution=attribution,
            reasoning=reasoning,
        )


__all__ = ["AttributionGate", "FailureReviewer", "_ALLOWED"]
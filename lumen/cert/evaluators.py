"""Three Evaluator Perspectives + VALID/INVALID + raw verdict semantics.

Canonical home: ``lumen/cert``.

Evaluation Contract (frozen):
* All three Perspectives share the **same** :class:`SharedCoreRubric` and judge
  the *whole turn*; they differ only in which failure mode they emphasize.
* Each run first emits ``evaluation_status`` = VALID | INVALID.
* Only a ``VALID`` run may carry ``decision`` ∈ {GO, NO_GO}; ``INVALID`` forces
  ``decision = None``.
* ``INVALID`` is reserved for execution-level problems (API failure, timeout,
  malformed output, missing input, model refusal). An evaluator that merely
  *judges wrongly* on a VALID run is an ``EVALUATOR`` attribution — it must not
  be laundered through ``INVALID``.
* Valid outputs must include: decision, criterion_id, affected_turn, evidence,
  severity, reason, confidence.

The Evaluator is read-only: it never mutates the tutor, learner, rubric or data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .llm import LLMCallError, ModelGateway
from .models import EvaluationResult, EvaluationStatus, RawVerdict
from .rubric import CORE_RUBRIC, SharedCoreRubric

logger = logging.getLogger(__name__)

#: Deterministic set so each evaluator has a stable id/criterion address.
PERSPECTIVES: dict[str, str] = {
    "correctness": "Correctness / harm-safety emphasis",
    "pedagogy": "Pedagogy / scaffolding / clarity emphasis",
    "context": "Context / learner-adaptation emphasis",
}

_OUTPUT_CONTRACT = (
    "Return ONLY a single JSON object (no markdown, no prose) with exactly "
    "these keys:\n"
    "{\n"
    '  "evaluation_status": "VALID" or "INVALID",\n'
    '  "decision": "GO" or "NO_GO" (null when evaluation_status is INVALID),\n'
    '  "criterion_id": "<short criterion id>",\n'
    '  "affected_turn": <int>,\n'
    '  "evidence": "<concrete quote/behavior from the tutor action or dialogue>",\n'
    '  "severity": "critical"|"major"|"minor",\n'
    '  "reason": "<why this turn is or is not acceptable>",\n'
    '  "confidence": <0.0-1.0>\n'
    "}\n"
    'INVALID is ONLY for an execution-level problem — the turn input is '
    "blank/missing, or you cannot perform the evaluation (still: judge the "
    "turn if ANY tutor text exists). A POOR, empty-of-real-teaching, stalled, "
    "or non-educational tutor reply is a VALID NO_GO (criterion "
    '"next_action"/"correctness"), NOT INVALID. Only a truly blank '
    '"tutor_action" (empty string) is INVALID.'
)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from a model reply."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.startswith("json"):
            body = body[4:].lstrip()
    if not body.startswith("{"):
        start = body.find("{")
        end = body.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        body = body[start : end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Evaluator:
    """One evaluator perspective; read-only, shares the Core Rubric."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        evaluator_id: str,
        perspective: str,
        rubric: SharedCoreRubric = CORE_RUBRIC,
    ) -> None:
        self._gateway = gateway
        self._evaluator_id = evaluator_id
        self._perspective = perspective
        self._rubric = rubric

    def _system_prompt(self) -> str:
        return (
            "You are an independent Lumen teaching-behavior Evaluator "
            f"({self._perspective}). You evaluate whether a SINGLE teaching "
            "turn is acceptable teaching behavior.\n"
            "You must judge the WHOLE turn against every criterion in the "
            "shared rubric below — you only emphasize one failure mode, you do "
            "not act as a partial grader."
            "\n\n"
            f"{self._rubric.to_prompt()}"
            "\n\n"
            f"{_OUTPUT_CONTRACT}"
        )

    @staticmethod
    def _turn_block(*, learner: str, tutor: str, prior: list[dict[str, Any]]) -> str:
        if not tutor.strip():
            return "TURN INPUT: tutor action text is EMPTY."
        lines = ["[Turn under evaluation]", f"learner_utterance: {learner}"]
        lines.append(f"tutor_action: {tutor}")
        if prior:
            lines.append("[prior_dialogue]")
            for m in prior:
                role = "tutor" if m.get("role") == "assistant" else "learner"
                content = str(m.get("content") or "")
                if content:
                    lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    async def run(
        self,
        *,
        episode_id: str,
        turn_index: int,
        learner_utterance: str,
        tutor_action: str,
        prior: list[dict[str, Any]],
    ) -> EvaluationResult:
        evaluation_id = f"{self._evaluator_id}:{episode_id}:t{turn_index}"
        # Deterministic input-missing → INVALID (execution-level), so the loop
        # never turns a blank tutor action into a graded NO_GO.
        if not str(tutor_action or "").strip():
            return EvaluationResult(
                evaluation_id=evaluation_id,
                episode_id=episode_id,
                turn_index=turn_index,
                evaluator_id=self._evaluator_id,
                evaluator_perspective=self._perspective,
                evaluation_status=EvaluationStatus.INVALID,
                decision=None,
                raw={"input": "blank tutor action"},
            )
        user_prompt = self._turn_block(
            learner=learner_utterance, tutor=tutor_action, prior=prior
        )
        try:
            raw_text = await self._gateway.complete(
                system_prompt=self._system_prompt(),
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=700,
                label=f"evaluator_{self._evaluator_id}",
            )
        except LLMCallError as exc:
            logger.warning("Evaluator %s execution failure: %s", self._evaluator_id, exc)
            return EvaluationResult(
                evaluation_id=evaluation_id,
                episode_id=episode_id,
                turn_index=turn_index,
                evaluator_id=self._evaluator_id,
                evaluator_perspective=self._perspective,
                evaluation_status=EvaluationStatus.INVALID,
                decision=None,
                raw={"err": str(exc)},
            )

        parsed = _extract_json(raw_text)
        if parsed is None:
            # Malformed output is an execution-level problem -> INVALID.
            return EvaluationResult(
                evaluation_id=evaluation_id,
                episode_id=episode_id,
                turn_index=turn_index,
                evaluator_id=self._evaluator_id,
                evaluator_perspective=self._perspective,
                evaluation_status=EvaluationStatus.INVALID,
                decision=None,
                raw={"malformed": raw_text[:500]},
            )

        status_raw = str(parsed.get("evaluation_status") or "").strip().upper()
        if status_raw != "VALID":
            return EvaluationResult(
                evaluation_id=evaluation_id,
                episode_id=episode_id,
                turn_index=turn_index,
                evaluator_id=self._evaluator_id,
                evaluator_perspective=self._perspective,
                evaluation_status=EvaluationStatus.INVALID,
                decision=None,
                raw=parsed,
            )

        decision_raw = str(parsed.get("decision") or "").strip().upper()
        verdict = None
        if decision_raw == "GO":
            verdict = RawVerdict.GO
        elif decision_raw == "NO_GO":
            verdict = RawVerdict.NO_GO
        else:
            # Missing/unknown decision on a VALID run violates the contract.
            return EvaluationResult(
                evaluation_id=evaluation_id,
                episode_id=episode_id,
                turn_index=turn_index,
                evaluator_id=self._evaluator_id,
                evaluator_perspective=self._perspective,
                evaluation_status=EvaluationStatus.INVALID,
                decision=None,
                raw=parsed,
            )

        try:
            confidence = float(parsed.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        return EvaluationResult(
            evaluation_id=evaluation_id,
            episode_id=episode_id,
            turn_index=turn_index,
            evaluator_id=self._evaluator_id,
            evaluator_perspective=self._perspective,
            evaluation_status=EvaluationStatus.VALID,
            decision=verdict,
            criterion_id=str(parsed.get("criterion_id") or ""),
            affected_turn=int(parsed.get("affected_turn") or turn_index),
            evidence=str(parsed.get("evidence") or ""),
            severity=str(parsed.get("severity") or ""),
            reason=str(parsed.get("reason") or ""),
            confidence=confidence,
            raw=parsed,
        )


def build_evaluator_suite(
    gateway: ModelGateway,
    *,
    perspective_ids: list[str] | None = None,
    rubric: SharedCoreRubric = CORE_RUBRIC,
) -> list[Evaluator]:
    ids = perspective_ids or list(PERSPECTIVES.keys())
    return [
        Evaluator(gateway, evaluator_id=pid, perspective=PERSPECTIVES[pid], rubric=rubric)
        for pid in ids
    ]


__all__ = ["Evaluator", "build_evaluator_suite", "PERSPECTIVES", "CORE_RUBRIC"]
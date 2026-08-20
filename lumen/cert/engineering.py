"""Engineering Agent — the ONLY role with Tutor mutation permission.

Canonical home: ``lumen/cert``.

Agent Permission Contract:
* The Engineering Agent is activated **only** when the Attribution Gate reports
  ``attribution = LUMEN`` (a confirmed Lumen tutor failure).
* It may mutate tutor **prompts** / **teaching policy** / **tutor-side
  configuration** by producing a NEW :class:`CandidateManifest` with a fresh
  ``effective_candidate_id`` (parent = the failed candidate). It never
  overwrites an old candidate.
* It is **forbidden** from editing the Rubric, Evaluators, Simulator, failure
  evidence, regression cases, or acceptance criteria.

A real code-level tutor defect (not fixable by prompt/config) is reported as an
"unpatchable" signal so the loop can escalate rather than pretend a candidate
patch fixed the root cause.
"""

from __future__ import annotations

import logging
from typing import Any

from .llm import LLMCallError, ModelGateway
from .models import CandidateManifest, FailureReview, content_digest

logger = logging.getLogger(__name__)


class UnpatchableFailure(RuntimeError):
    """The confirmed LUMEN failure cannot be fixed by prompt/config mutation."""


class EngineeringAgent:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    @staticmethod
    def _candidate_from(base: CandidateManifest, **overrides: Any) -> CandidateManifest:
        tutor_config = dict(base.tutor_config)
        base_fields = {
            "parent_candidate_id": base.effective_candidate_id,
            "tutor_config": tutor_config,
            "prompt_override": base.prompt_override,
            "temperature": base.temperature,
        }
        base_fields.update(overrides)
        # id is derived from content so a changed candidate yields a NEW id and
        # an unchanged one is rejected (never silent-overwrite).
        return CandidateManifest(
            effective_candidate_id="cand-"
            + content_digest({k: base_fields[k] for k in ("tutor_config", "prompt_override", "temperature")})[:24],
            parent_candidate_id=base.effective_candidate_id,
            content_digest=content_digest(
                {k: base_fields[k] for k in ("tutor_config", "prompt_override", "temperature")}
            ),
            tutor_config=base_fields["tutor_config"],
            prompt_override=base_fields["prompt_override"],
            temperature=float(base_fields["temperature"]),
        )

    async def place_patch(
        self,
        *,
        review: FailureReview,
        base_candidate: CandidateManifest,
        existing_full: list[str] | None = None,
    ) -> CandidateManifest:
        """Produce a mutated Tutor candidate targeting the *confirmed* failure.

        ``existing_full`` = complete tutor actions already certified as OK (the
        previous candidates' prompt overrides), to steer the LLM away from
        regressing them.
        """
        criterion = ""
        evidence = ""
        for r in review.non_go:
            ev = (r.get("evidence") or "") if isinstance(r, dict) else getattr(r, "evidence", "")
            cr = (r.get("criterion_id") or "") if isinstance(r, dict) else getattr(r, "criterion_id", "")
            if ev or cr:
                criterion = cr
                evidence = ev
                break

        current_prompt = (
            base_candidate.prompt_override
            or "Use Lumen's real mastery teaching instructions as the base."
        )
        context = (
            "You are the Engineering Agent inside a teaching-behavior "
            "certification loop. A CONFIRMED Lumen failure was attributed to the "
            "TUTOR (not the evaluator/simulator/rubric).\n"
            "Produce an improved TUTOR system prompt (English, 4-8 sentences). "
            "The tutor has NO tools and NO engine: it must TEACH DIRECTLY in its "
            "own reply and must never mention checking a plan, graph, engine, "
            "tool, or 'setting up' anything.\n"
            "THE RESPONSE MUST BE CONCISE: keep each turn to roughly 100-200 "
            "words, well-scoped, and ALWAYS end by asking the learner one short "
            "question or giving one small exercise. NEVER write long markdown "
            "tables, multi-section dumps, or huge examples that could be "
            "truncated.\n"
            "ANY example you give must be FACTUALLY correct and internally "
            "consistent (e.g. a stated byte length must match the shown body).\n"
            f"Failing criterion: {criterion}\n"
            f"Evaluator evidence: {evidence}\n\n"
            f"Current tutor prompt:\n{current_prompt}\n\n"
            "Return ONLY the new tutor system prompt text (no surrounding prose)."
        )
        try:
            new_prompt = await self._gateway.complete(
                system_prompt=context,
                user_prompt="",
                temperature=0.2,
                max_tokens=500,
                label="engineering",
            )
        except LLMCallError as exc:
            raise UnpatchableFailure(f"engineering mutation LLM failed: {exc}") from exc

        new_prompt = new_prompt.strip()
        if not new_prompt:
            raise UnpatchableFailure("engineering mutation returned an empty prompt")

        new_candidate = self._candidate_from(
            base_candidate, prompt_override=new_prompt, temperature=base_candidate.temperature
        )
        if new_candidate.effective_candidate_id == base_candidate.effective_candidate_id:
            raise UnpatchableFailure("engineering mutation produced an identical candidate")
        return new_candidate


__all__ = ["EngineeringAgent", "UnpatchableFailure"]
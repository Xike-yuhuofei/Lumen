"""The Lumen Tutor under certification — runs the **real** Lumen teaching path.

Canonical home: ``lumen/cert``.

Fidelity principle (Contract: *"must run the real Lumen Tutor path, not a fake
behavior-different tutor"*): this Tutor does **not** implement bespoke
behavior. Per turn it composes the teaching inputs from the real Lumen
components that govern tutor behavior in production:

* the **real teaching instruction prompt** — the exact file the production
  ``MasteryLoopCapability.system_block`` serves
  (``lumen/modes/learn/prompts/{zh,en}/system.md``);
* the **real teaching policy** — ``lumen.modes.learn.TeachingService.decide(path_id)``
  over the real ``LearningStore`` learner state, when a learning path is bound
  (the production next-action policy: diagnostic / teach / practice / review /
  complete); and
* the **real Lumen LLM** — ``lumen.cert.RealLumenGateway`` -> the unified
  ``lumen.shared._util.llm.complete`` factory the production agent-loop model
  uses.

The only thing the Engineering Agent may mutate across a Candidate is
``prompt_override`` (prompt) and ``temperature`` (tutor-side configuration) —
never the Rubric / Evaluators / Simulator / Regression cases / evidence.
"""

from __future__ import annotations

from importlib import resources
import logging
from typing import Any

from .llm import ModelGateway
from .models import CandidateManifest

logger = logging.getLogger(__name__)

#: A tutor episode never grows context forever; 10 turns is the certification
#: horizon and the conversation cap keeps the prompt bounded.
MAX_CONVERSATION_TURNS = 10


def load_real_teaching_prompt(language: str) -> str:
    """Return the real Lumen tutor instruction text for ``language``.

    This is the exact prompt ``MasteryLoopCapability.system_block`` loads in
    production (``lumen/modes/learn/prompts/{lang}/system.md``); reading it
    here keeps the certified tutor's instructions identical to Lumen's own.
    """
    from lumen.modes.learn.loop_capability import MasteryLoopCapability, _prompt_text  # noqa: F401

    lang = "zh" if str(language or "en").lower().startswith("zh") else "en"
    try:
        path = resources.files("lumen.modes.learn.prompts").joinpath(lang, "system.md")
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load real mastery prompt; using header only", exc_info=True)
    return (
        "You are Lumen, a Lumen mastery tutor. Respond in the learner's "
        "language. Keep teaching well-scoped."
    )


def load_teaching_policy_hint(path_id: str) -> str:
    """Ask the real Lumen teaching policy what to do next for ``path_id``.

    Returns a short human hint guiding the tutor (diagnostic / teach /
    practice / review / complete), or ``""`` when no path/policy is available.
    Uses the real ``TeachingService`` over the real ``LearningStore``.
    """
    try:
        from lumen.modes.learn.application.teaching_service import TeachingService

        action = TeachingService().decide(path_id)
        hint = f"[Lumen teaching policy for path {path_id}]: {action.action.value}"
        reason = getattr(action, "reason", "") or ""
        if reason:
            hint += f" — {reason}"
        return hint
    except Exception as exc:  # noqa: BLE001
        logger.debug("Teaching policy unavailable for %s: %s", path_id, exc)
        return ""


class LumenTutor:
    """Real Lumen teaching behavior under a Candidate configuration."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        candidate: CandidateManifest,
        language: str = "en",
    ) -> None:
        self._gateway = gateway
        self._candidate = candidate
        self._language = language
        cfg = candidate.tutor_config or {}
        self._scenario = {
            "subject": str(cfg.get("subject") or "the topic"),
            "goal": str(cfg.get("goal") or ""),
            "knowledge_points": list(cfg.get("knowledge_points") or []),
            "path_id": str(cfg.get("path_id") or "").strip(),
            "perspective": str(cfg.get("learner_profile") or "a curious adult beginner"),
        }

    # -- prompt assembly ------------------------------------------------------

    def _system_prompt(self) -> str:
        base = (
            self._candidate.prompt_override
            if (self._candidate.prompt_override or "").strip()
            else load_real_teaching_prompt(self._language)
        )
        scenario_lines = [
            f"Teaching scenario: {self._scenario['subject']}.",
        ]
        if self._scenario["goal"]:
            scenario_lines.append(f"Learning goal: {self._scenario['goal']}.")
        if self._scenario["knowledge_points"]:
            scenario_lines.append(
                "Mastery knowledge points: " + "; ".join(self._scenario["knowledge_points"])
            )
        scenario_lines.append(
            f"Learner profile: {self._scenario['perspective']}. Respond in the "
            f"{'learner’s language as established above' if self._language.startswith('zh') or self._language == 'zh' else 'learner’s language established in the dialogue'}."
        )
        return "\n\n".join([base, "[Scenario]", "\n".join(scenario_lines)])

    def _build_messages(
        self,
        *,
        prior_conversation: list[dict[str, Any]],
        learner_utterance: str,
        turn_index: int,
    ) -> list[dict[str, Any]]:
        policy_hint = ""
        if self._scenario["path_id"]:
            policy_hint = load_teaching_policy_hint(self._scenario["path_id"])
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt()}]
        if policy_hint:
            messages.append({"role": "system", "content": policy_hint})
        for msg in prior_conversation[-MAX_CONVERSATION_TURNS:]:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": learner_utterance})
        return messages

    # -- turn execution -------------------------------------------------------

    async def run_turn(
        self,
        *,
        turn_index: int,
        prior_conversation: list[dict[str, Any]],
        learner_utterance: str,
    ) -> str:
        """Produce one Lumen Teaching Action for the given learner utterance.

        Returns the tutor's utterance text (feedback / explanation / scaffold /
        question / next teaching action).
        """
        messages = self._build_messages(
            prior_conversation=prior_conversation,
            learner_utterance=learner_utterance,
            turn_index=turn_index,
        )
        system_prompt = messages[0]["content"]
        user_prompt = "\n\n".join(
            (f"{m['role']}: {m['content']}" if m["role"] != "system" else "")
            for m in messages
            if m["role"] != "system"
        )
        return await self._gateway.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._candidate.temperature,
            max_tokens=4000,
            label="tutor",
        )


__all__ = ["LumenTutor", "load_real_teaching_prompt", "load_teaching_policy_hint"]
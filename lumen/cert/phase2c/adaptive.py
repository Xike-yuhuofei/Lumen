"""Phase 2C — adaptive Teaching Strategy selection (deterministic & auditable).

Canonical home: ``lumen/cert/phase2c``.

Phase 2C moves from "one global static prompt" to **choosing the more
appropriate Teaching Strategy per turn**. The selection must use only what the
real Tutor can legitimately see at runtime — the public conversation and the
current learner utterance — and must never read hidden learner state, Evaluator
feedback or Diagnosis information.

Design (minimal, deterministic, auditable — no new selection model):
* A small, topic-generic heuristic (:class:`AdaptiveStrategySelector`) reads the
  current learner utterance and decides between two materially different,
  already-validated strategies — ``socratic-questions`` (elicit reasoning) and
  ``diagnose-first`` (explicitly correct a voiced claim) — falling back to the
  default teaching mode otherwise.
* Every decision records *why* (rationale) and *the observable evidence it used*
  (the signals that fired), so "this turn chose strategy X because of observable
  state Y" is fully traceable.
* :class:`AdaptiveLumenTutor` wraps the real :class:`lumen.cert.tutor.LumenTutor`
  and injects the selected strategy as a per-turn ``strategy_directive`` in the
  real teaching prompt — the same real Lumen teaching path, parameterized
  per-turn.

The candidate identity for the adaptive arm is a real ``CandidateManifest`` whose
``prompt_override`` documents the adaptive policy (so regression/wellformed still
see a bounded, self-describing candidate); at runtime the per-turn directive
(computed by the selector) overrides it.

Scope is Teaching Behaviour Quality / Long-Horizon Teaching Stability only.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..models import CandidateManifest, content_digest
from ..phase2.scenarios import STRATEGIES
from ..tutor import LumenTutor

#: The adaptive experimental arm's strategy id (a candidate identity tag, not a
#: single directive like phase2's fixed strategies).
ADAPTIVE_STRATEGY_ID = "adaptive"

#: Inner strategies the selector may choose between per turn. These are existing,
#: validated phase2 strategies (Phase 2B promoted ``socratic-questions``; we keep
#: that result as an asset). ``baseline`` = the default teaching prompt.
SOCRATIC = "socratic-questions"
DIAGNOSE_FIRST = "diagnose-first"
BASELINE = "baseline"

AVAILABLE_STRATEGIES = (SOCRATIC, DIAGNOSE_FIRST, BASELINE)

#: Strong-confidence / factual-claim markers (topic-generic). A learner utterance
#: that voices one of these is treated as a "strongly-worded claim" that a tutor
#: should diagnose & correct before building on it. High-precision on purpose:
#: ``sure``/``can't``/``can`` are excluded so negated or merely-uncertain phrasing
#: ("not sure", "can't be") never fires.
_STRONG_CLAIM_MARKERS: frozenset[str] = frozenset({
    "is always", "always more", "is never",
    "proves", "proven", "must be",
    "definitely", "certainly", "obviously", "clearly",
    "is just", "are just", "is basically", "is essentially",
    "is the same as", "the same as", "equates", "means that",
    "guarantee",
})

#: The adaptive policy is documented in the candidate's ``prompt_override`` so the
#: manifest is self-describing and bounded. It is NOT injected as-is at runtime —
#: the selector computes the concrete per-turn directive instead.
ADAPTIVE_POLICY = (
    "ADAPTIVE STRATEGY POLICY (choose per turn from observable learner behaviour):\n"
    "- If the learner has not yet voiced a substantive claim (opening or a short "
    "backchannel reply), teach by asking short questions to elicit their reasoning.\n"
    "- If the learner voices a strongly-worded claim (an overconfident assertion "
    "of a prior or assumption), diagnose that claim first and correct it before "
    "building on it.\n"
    "- Otherwise teach with the default mode."
)


@dataclass(slots=True)
class StrategyDecision:
    """One auditable per-turn strategy choice.

    ``strategy_id`` is what was actually applied for the turn;
    ``rationale``/``evidence`` explain *why* from the observable public signal.
    """

    turn_index: int
    strategy_id: str
    rationale: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "strategy_id": self.strategy_id,
            "rationale": self.rationale,
            "evidence": self.evidence,
        }


def strategy_directive(strategy_id: str) -> str:
    """Return the teaching directive for a strategy id (``""`` for baseline)."""
    if strategy_id == BASELINE:
        return ""
    return str(STRATEGIES[strategy_id]["directive"])


def _is_opening(turn_index: int, text: str) -> bool:
    t = text.strip().lower()
    if turn_index <= 1:
        return True
    return any(m in t for m in ("i want to learn", "let's start", "i'm ready", "ready when you are"))


_BACKCHANNEL_TOKENS = frozenset({
    "ok", "okay", "i", "see", "got", "it", "makes", "sense", "understood",
    "right", "good", "gotcha", "alright", "yes", "yeah", "sure", "great",
    "perfect", "thanks", "that",
})


def _is_backchannel(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if len(t) < 15:
        return True
    tokens = set(re.findall(r"[a-z]+'?[a-z]*", t))
    if not tokens:
        return True
    # A backchannel is an utterance made only of acknowledgment words. A wordy
    # claim that merely *contains* "right" / "ok" is NOT a backchannel.
    return len(tokens - _BACKCHANNEL_TOKENS) == 0


def _is_strong_claim(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 20:
        return False
    return any(m in t for m in _STRONG_CLAIM_MARKERS)


class AdaptiveStrategySelector:
    """Deterministic, auditable per-turn strategy selection from public signals.

    Only uses the current learner utterance / turn index (public dialogue) — it
    never touches hidden learner state, Evaluator output or Diagnosis.
    """

    def select(
        self,
        *,
        turn_index: int,
        prior_conversation: list[dict[str, Any]],
        learner_utterance: str,
    ) -> StrategyDecision:
        text = str(learner_utterance or "")
        if _is_opening(turn_index, text) or _is_backchannel(text):
            return StrategyDecision(
                turn_index=turn_index,
                strategy_id=SOCRATIC,
                rationale=(
                    "learner has not yet voiced a substantive claim (opening or a "
                    "short backchannel reply); elicit their reasoning with questions"
                ),
                evidence=f"opening/backchannel utterance, turn {turn_index}",
            )
        if _is_strong_claim(text):
            return StrategyDecision(
                turn_index=turn_index,
                strategy_id=DIAGNOSE_FIRST,
                rationale=(
                    "learner voiced a strongly-worded claim (overconfident assertion "
                    "of a prior or assumption); diagnose and correct it before "
                    "building on it"
                ),
                evidence=f"strong-claim marker in learner utterance, turn {turn_index}",
            )
        return StrategyDecision(
            turn_index=turn_index,
            strategy_id=BASELINE,
            rationale=(
                "substantive but not a strong claim and not a backchannel; "
                "teach with the default mode"
            ),
            evidence=f"neutral substantive utterance, turn {turn_index}",
        )


class AdaptiveLumenTutor(LumenTutor):
    """Real Lumen Tutor whose per-turn directive is chosen adaptively.

    Records every per-turn :class:`StrategyDecision` on ``strategy_decisions`` so
    the resulting Episode is fully auditable ("which strategy this turn, why").
    """

    def __init__(
        self,
        gateway: Any,
        *,
        candidate: CandidateManifest,
        language: str = "en",
        selector: AdaptiveStrategySelector | None = None,
    ) -> None:
        super().__init__(gateway, candidate=candidate, language=language)
        self._selector = selector or AdaptiveStrategySelector()
        self.strategy_decisions: list[dict[str, Any]] = []

    async def run_turn(
        self,
        *,
        turn_index: int,
        prior_conversation: list[dict[str, Any]],
        learner_utterance: str,
    ) -> str:
        decision = self._selector.select(
            turn_index=turn_index,
            prior_conversation=prior_conversation,
            learner_utterance=learner_utterance,
        )
        self.strategy_decisions.append(decision.to_dict())
        directive = strategy_directive(decision.strategy_id)
        return await super().run_turn(
            turn_index=turn_index,
            prior_conversation=prior_conversation,
            learner_utterance=learner_utterance,
            strategy_directive=directive,
        )


def build_adaptive_candidate(
    *,
    scenario: dict[str, Any],
    base_prompt: str,
    strategy_id: str = ADAPTIVE_STRATEGY_ID,
) -> CandidateManifest:
    """Build the adaptive-arm candidate manifest.

    The scenario's ``tutor_config`` is shared with the fixed arms (fair
    condition); ``strategy_tag="adaptive"`` marks the arm. ``prompt_override``
    documents the adaptive policy on top of the real base prompt (bounded, so the
    regression wellformed gate still passes); the per-turn directive is computed
    at runtime by the selector, not read from this override.
    """
    base = (base_prompt or "").strip()
    cfg = dict(scenario["tutor_config"])
    cfg["strategy_tag"] = strategy_id
    prompt_override = (base + "\n\n" + ADAPTIVE_POLICY) if base else ADAPTIVE_POLICY
    temperature = 0.2
    payload = {
        "tutor_config": cfg,
        "prompt_override": prompt_override,
        "temperature": temperature,
    }
    digest = content_digest(payload)
    cid = f"p2c-{scenario['id']}-{strategy_id}-{digest[:16]}"
    return CandidateManifest(
        effective_candidate_id=cid,
        parent_candidate_id=None,
        content_digest=digest,
        tutor_config=cfg,
        prompt_override=prompt_override,
        temperature=temperature,
    )


def strategy_mix(strategy_decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate selected-strategy usage across an adaptive episode (or a list of
    decisions from multiple episodes).

    Returns ``{by_strategy: {sid: count}, total, dominant_strategy,
    dominant_ratio}``. The dominant ratio is the anti-degeneration signal: an
    adaptive arm that always picks one strategy (ratio ≈ 1.0) is indistinguishable
    from that fixed strategy, so it can't claim value *from selection*.
    """
    counts: dict[str, int] = {}
    for d in strategy_decisions:
        sid = str(d.get("strategy_id") or BASELINE)
        counts[sid] = counts.get(sid, 0) + 1
    total = sum(counts.values())
    if not total:
        return {"by_strategy": {}, "total": 0, "dominant_strategy": None, "dominant_ratio": 0.0}
    dominant = max(counts, key=counts.get)
    return {
        "by_strategy": counts,
        "total": total,
        "dominant_strategy": dominant,
        "dominant_ratio": round(counts[dominant] / total, 4),
    }


@dataclass(slots=True)
class AdaptiveTutorBundle:
    """Carries the adaptive tutor + its candidate so runners can reuse it."""

    candidate: CandidateManifest
    tutor: AdaptiveLumenTutor


__all__ = [
    "ADAPTIVE_STRATEGY_ID",
    "SOCRATIC",
    "DIAGNOSE_FIRST",
    "BASELINE",
    "AVAILABLE_STRATEGIES",
    "ADAPTIVE_POLICY",
    "StrategyDecision",
    "strategy_directive",
    "AdaptiveStrategySelector",
    "_is_strong_claim",
    "_is_opening",
    "_is_backchannel",
    "AdaptiveLumenTutor",
    "build_adaptive_candidate",
    "strategy_mix",
]
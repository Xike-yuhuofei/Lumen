"""Phase 2A — real-LLM strategy comparison runner.

Canonical home: ``lumen/cert/phase2``.

Runs one strategy ``candidate`` over one ``scenario`` as an N-turn Episode that
reuses the **real** Lumen planes (no parallel experiment system):

* Teaching plane via ``LumenTutor`` + ``LearnerSimulator`` (the exact Phase 1
  plane);
* Evaluation plane via the three Evaluator Perspectives over the same
  ``SharedCoreRubric``;
* Persistence via ``CertificationStore`` (append-only turn/evaluation trace).

Unlike the Phase 1 ``CertificationController`` control plane, this comparator
does **not** run the Attribution / Engineering patch loop: a strategy comparison
must measure each candidate's *native* teaching behaviour, not the automatic
mutation that Phase 1 uses to converge one candidate. NO_GO turns are recorded,
never silently promoted. This is exactly the "no gaming, no weakening" rule.

Plane discipline is inherited: the Tutor and Simulator only ever see public
conversation; the Evaluators are read-only; evaluation output never leaks into
the Teaching plane.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

from ..engine import build_contexts
from ..evaluators import build_evaluator_suite
from ..llm import ModelGateway
from ..models import (
    CandidateManifest,
    Episode,
    EpisodeEnd,
    EvaluationStatus,
    FinalTurnStatus,
    RawVerdict,
    TurnArtifact,
)
from ..planes import EvaluationPlane, TeachingPlane
from ..simulator import LearnerSimulator
from ..store import CertificationStore
from ..tutor import LumenTutor
from .scenarios import EVAL_CONFIG

logger = logging.getLogger(__name__)


def _final_status(results: list[Any]) -> FinalTurnStatus:
    """Derive a final turn status from raw evaluator results.

    * all VALID + all GO        -> PASS
    * any INVALID               -> UNRESOLVED (infra, not a teaching judgement)
    * any VALID NO_GO           -> FAIL (native failure of the strategy)
    """
    if not results:
        return FinalTurnStatus.UNRESOLVED
    if any(r.evaluation_status != EvaluationStatus.VALID for r in results):
        return FinalTurnStatus.UNRESOLVED
    if all(r.decision == RawVerdict.GO for r in results):
        return FinalTurnStatus.PASS
    return FinalTurnStatus.FAIL


def _aggregate(per_turn: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_turn)
    n_pass = sum(1 for t in per_turn if t["final_status"] == "PASS")
    n_fail = sum(1 for t in per_turn if t["final_status"] == "FAIL")
    n_unres = n - n_pass - n_fail
    go = sum(t["go_count"] for t in per_turn)
    no_go = sum(t["no_go_count"] for t in per_turn)
    invalid = sum(t["invalid_count"] for t in per_turn)
    confs = [c for t in per_turn for c in t["confidence"]]
    mean_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
    episode = EpisodeEnd.PASS if n and n_pass == n else (
        EpisodeEnd.FAIL if n_fail else EpisodeEnd.BLOCKED
    )
    return {
        "n_turns": n,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_unresolved": n_unres,
        "all_pass": n > 0 and n_pass == n,
        "pass_rate": round(n_pass / n, 4) if n else 0.0,
        "go_total": go,
        "no_go_total": no_go,
        "invalid_total": invalid,
        "mean_confidence": mean_conf,
        "episode_status": episode.value,
    }


async def run_episode(
    *,
    gateway: ModelGateway,
    store: CertificationStore,
    candidate: CandidateManifest,
    scenario: dict[str, Any],
    max_turns: int = 10,
    language: str = "en",
    episode_id: str | None = None,
) -> dict[str, Any]:
    """Run a single strategy candidate across an N-turn Episode and return a
    structured, persisted comparison report."""
    context_scenario = {"subject": scenario["tutor_config"]["subject"]}
    contexts = build_contexts(scenario=context_scenario, evaluation_config=EVAL_CONFIG)
    store.put_candidate(candidate)
    store.put_context(contexts)

    rid = episode_id or f"ep-p2a-{uuid.uuid4().hex[:20]}"
    store.create_episode(
        Episode(
            episode_id=rid,
            candidate_id=candidate.effective_candidate_id,
            trajectory_context_id=contexts.trajectory_context_id,
            evaluation_context_id=contexts.evaluation_context_id,
        )
    )

    plane = TeachingPlane(
        tutor=LumenTutor(gateway, candidate=candidate, language=language),
        simulator=LearnerSimulator(gateway, candidate=candidate),
    )
    eval_plane = EvaluationPlane(build_evaluator_suite(gateway))

    history: list[dict[str, Any]] = []
    subject = str(scenario["tutor_config"]["subject"])
    learner = f"I want to learn {subject}."
    per_turn: list[dict[str, Any]] = []

    for turn in range(1, max_turns + 1):
        tutor_action = await plane.teach(
            turn_index=turn, history=history, learner_utterance=learner
        )
        sim = await plane.respond_like_learner(
            turn_index=turn, history=history, tutor_action=tutor_action
        )
        public_history = [dict(m) for m in history]
        store.append_turn(
            TurnArtifact(
                episode_id=rid,
                turn_index=turn,
                learner_utterance=learner,
                tutor_action=tutor_action,
                prior_conversation=public_history,
                hidden_learner_state=dict(sim["hidden"]),
            )
        )
        history.append({"role": "user", "content": learner})
        history.append({"role": "assistant", "content": tutor_action})

        results = await eval_plane.evaluate_turn(
            episode_id=rid,
            turn_index=turn,
            learner_utterance=learner,
            tutor_action=tutor_action,
            prior=public_history,
        )
        for r in results:
            store.append_evaluation(r)

        status = _final_status(results)
        store.set_turn_final_status(rid, turn, status.value)
        verdicts = {
            r.evaluator_id: {
                "decision": r.decision.value if r.decision else None,
                "evaluation_status": r.evaluation_status.value,
                "confidence": r.confidence,
            }
            for r in results
        }
        go_count = sum(1 for r in results if r.decision == RawVerdict.GO)
        no_go_count = sum(1 for r in results if r.decision == RawVerdict.NO_GO)
        invalid_count = sum(1 for r in results if r.evaluation_status != EvaluationStatus.VALID)
        per_turn.append(
            {
                "turn_index": turn,
                "learner_utterance": learner,
                "tutor_action": tutor_action,
                "final_status": status.value,
                "verdicts": verdicts,
                "go_count": go_count,
                "no_go_count": no_go_count,
                "invalid_count": invalid_count,
                "confidence": [r.confidence for r in results if r.evaluation_status == EvaluationStatus.VALID],
            }
        )
        learner = str(sim["utterance"])

    agg = _aggregate(per_turn)
    store.finish_episode(rid, EpisodeEnd(agg["episode_status"]), max_turns)

    return {
        "scenario_id": scenario["id"],
        "strategy_id": candidate_prompt_tag(candidate),
        "effective_candidate_id": candidate.effective_candidate_id,
        "episode_id": rid,
        "trajectory_context_id": contexts.trajectory_context_id,
        "evaluation_context_id": contexts.evaluation_context_id,
        "temperature": candidate.temperature,
        "prompt_override_cut": (candidate.prompt_override or "")[:120],
        "language": language,
        **agg,
        "per_turn": per_turn,
    }


def candidate_prompt_tag(candidate: CandidateManifest) -> str:
    """Best-effort short tag of the strategy from the manifest (no round-trip)."""
    cfg = candidate.tutor_config or {}
    sid = str(cfg.get("strategy_tag") or "")
    if sid:
        return sid
    # Fallback: strategy name was embedded in the candidate id ``p2a-<scen>-<strategy>-...``.
    rest = candidate.effective_candidate_id.split("-", 3)
    return rest[2] if len(rest) >= 3 else candidate.effective_candidate_id


__all__ = ["run_episode", "_final_status", "_aggregate"]
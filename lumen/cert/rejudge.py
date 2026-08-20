"""Evaluation-only Change re-adjudication runner for Phase 1 certification.

Canonical home: ``lumen/cert``.

This closes the last Phase 1 acceptance gap: a *dedicated running verification*
of the **Evaluation-only Change path**. When only the Rubric / Evaluator
Configuration changes and the Teaching Trace is unchanged, Phase 1 must:

* **retain** the existing immutable trace (the source turn artifacts are read
  only and never ``UPDATE``d);
* derive a **new EvaluationContext id** from the new ``evaluation_config``
  (trajectory digest is left identical — that is what proves the trace was not
  touched);
* **re-adjudicate every existing Turn** under that one new EvaluationContext
  (unified new rubric version + evaluator config), not a mix of old/new;
* keep every **result & version relationship traceable**: same trajectory ctx,
  old eval ctx → new eval ctx, new rubric version, per-turn verdicts, and the
  owning candidate id.

Plane discipline: this runner is **evaluation-plane + control-plane only**. It
never reads the hidden learner state for adjudication, never mutates the Tutor,
and never writes through the Attribution Gate / Engineering Agent. A changed
Rubric is an ``RUBRIC`` domain concern fixed in the harness, never a Lumen
mutation.

Usage::

    python -m lumen.cert.rejudge --episode ep-... --db data/.../cert_phase1.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import Any

from .engine import build_contexts
from .evaluators import build_evaluator_suite
from .llm import ModelGateway, MultiModelGateway
from .models import (
    Episode,
    EpisodeEnd,
    EvaluationResult,
    FinalTurnStatus,
    TurnArtifact,
)
from .planes import EvaluationPlane
from .rubric import SharedCoreRubric
from .store import CertificationStore

logger = logging.getLogger(__name__)


def next_rubric(version: str = "phase1-core-1.1") -> SharedCoreRubric:
    """A new Evaluation-Plane rubric (same criterion set, refined wording).

    Changing rubric *version* changes ``evaluation_digest`` → new
    ``evaluation_context_id`` while the trajectory digests stays fixed. The
    criterion *set* is kept identical so the re-adjudication is a true
    evaluation-only change, not a redefinition of what counts as acceptable.
    """
    from .rubric import Criterion, SharedCoreRubric

    return SharedCoreRubric(
        version=version,
        criteria=(
            Criterion(
                "correctness",
                "Factual correctness & harm-safety",
                "The tutor's statements are factually correct, contain no "
                "harmful/gaslighting content, any misconception is corrected, "
                "and no universal/absolute claim about a protocol or format is "
                "made unless it is truly universal (e.g. distinguish HTTP/1.x "
                "start-line vs HTTP/2/3 binary framing).",
            ),
            Criterion(
                "pedagogy_scaffolding",
                "Pedagogical scaffolding & clarity",
                "The tutor scaffolds with clarity: actionable feedback/explanation "
                "appropriate to the learner's stated level, breaks ideas down "
                "without dumping jargon, keeps each action well-scoped.",
            ),
            Criterion(
                "context_adaptation",
                "Learner/context adaptation & continuity",
                "The tutor adapts to what the learner just said, references prior "
                "dialogue consistently, does not contradict the conversation, and "
                "advances the learning episode coherently.",
            ),
            Criterion(
                "next_action",
                "Next teaching action",
                "The turn ends with an appropriate next teaching action "
                "(feedback/explanation/scaffold/question/next exercise) that gives "
                "the learner a clear way forward rather than a dead end.",
            ),
        ),
    )


def _derive_final_status(results: list[EvaluationResult]) -> FinalTurnStatus:
    """Final turn status for a re-adjudicated turn (immutable trace)."""
    if any(r.evaluation_status.value == "INVALID" for r in results):
        return FinalTurnStatus.UNRESOLVED
    if all(
        r.evaluation_status.value == "VALID"
        and (r.decision.value if r.decision else None) == "GO"
        for r in results
    ):
        return FinalTurnStatus.PASS
    return FinalTurnStatus.FAIL


async def rejudge_episode(
    *,
    gateway: ModelGateway,
    store: CertificationStore,
    source_episode_id: str,
    scenario: dict[str, Any],
    new_evaluation_config: dict[str, Any],
    new_rubric: SharedCoreRubric | None = None,
    old_evaluation_config: dict[str, Any] | None = None,
    language: str = "en",
    rejudge_episode_id: str | None = None,
) -> dict[str, Any]:
    """Re-adjudicate an existing episode's immutable trace under a new
    EvaluationContext. Returns a traceable report; never mutates the trace."""
    src = store.get_episode(source_episode_id)
    if src is None:
        raise ValueError(f"unknown source episode: {source_episode_id}")
    turns = store.get_turns(source_episode_id)
    if not turns:
        raise ValueError(f"source episode has no turns: {source_episode_id}")

    # Trajectory-specific fields are carried over unchanged; only the
    # evaluation digest may differ -> new evaluation_context_id.
    new_contexts = build_contexts(
        scenario=scenario, evaluation_config=new_evaluation_config
    )
    if new_contexts.trajectory_context_id != src["trajectory_context_id"]:
        # Same scenario must produce the identical trajectory id; if the caller
        # passed a different scenario this is not an evaluation-only change.
        raise ValueError(
            "trajectory changed (not evaluation-only): "
            f"{src['trajectory_context_id']} != {new_contexts.trajectory_context_id}"
        )
    store.put_context(new_contexts)

    rubric = new_rubric or next_rubric()
    evaluators = build_evaluator_suite(gateway, rubric=rubric)
    eval_plane = EvaluationPlane(evaluators)

    rid = rejudge_episode_id or f"ep-rejudge-{os.urandom(8).hex()[:16]}"
    rejudge_ep = Episode(
        episode_id=rid,
        candidate_id=src["candidate_id"],
        trajectory_context_id=src["trajectory_context_id"],
        evaluation_context_id=new_contexts.evaluation_context_id,
    )
    store.create_episode(rejudge_ep)

    per_turn: list[dict[str, Any]] = []
    all_pass = True
    for t in turns:
        turn_index = int(t["turn_index"])
        prior = list(t["prior_conversation"] or [])
        results = await eval_plane.evaluate_turn(
            episode_id=rid,
            turn_index=turn_index,
            learner_utterance=t["learner_utterance"],
            tutor_action=t["tutor_action"],
            prior=prior,
        )
        for r in results:
            store.append_evaluation(r)
        final_status = _derive_final_status(results)
        if final_status != FinalTurnStatus.PASS:
            all_pass = False
        # Immutable copy of the same trace row, owned by the rejudge episode.
        store.append_turn(
            TurnArtifact(
                episode_id=rid,
                turn_index=turn_index,
                learner_utterance=t["learner_utterance"],
                tutor_action=t["tutor_action"],
                prior_conversation=prior,
                hidden_learner_state=dict(t["hidden_learner_state"] or {}),
                final_status=final_status,
            )
        )
        store.set_turn_final_status(rid, turn_index, final_status.value)
        per_turn.append(
            {
                "turn_index": turn_index,
                "decisions": [
                    (r.evaluator_id, r.evaluation_status.value, r.decision.value if r.decision else None)
                    for r in results
                ],
                "final_status": final_status.value,
            }
        )

    status = EpisodeEnd.PASS if all_pass else (
        EpisodeEnd.FAIL
        if any(pt["final_status"] == "FAIL" for pt in per_turn)
        else EpisodeEnd.BLOCKED
    )
    store.finish_episode(rid, status, len(turns))

    old_contexts = store.get_context(
        src["trajectory_context_id"], src["evaluation_context_id"]
    )
    return {
        "kind": "evaluation-only-change",
        "source_episode_id": source_episode_id,
        "rejudge_episode_id": rid,
        "candidate_id": src["candidate_id"],
        # Traceability / version relationship:
        "trajectory_context_id": src["trajectory_context_id"],
        "trajectory_digest": (old_contexts or {}).get("trajectory_digest"),
        "old_evaluation_context_id": src["evaluation_context_id"],
        "old_evaluation_digest": (old_contexts or {}).get("evaluation_digest"),
        "old_rubric_version": (old_evaluation_config or {}).get("rubric_version", "phase1-core-1.0"),
        "new_evaluation_context_id": new_contexts.evaluation_context_id,
        "new_evaluation_digest": new_contexts.evaluation_digest,
        "new_rubric_version": rubric.version,
        "num_turns_rejudged": len(turns),
        "trace_unchanged": True,  # source turn rows were only read
        "status": status.value,
        "per_turn": per_turn,
        "all_pass": all_pass,
    }


def build_role_gateway() -> MultiModelGateway:
    """Reuse the same per-role model routing used by the real certification run."""
    from .run import build_role_gateway as _build

    return _build()


async def run(
    *,
    episode_id: str,
    db_path: str,
    new_rubric_version: str = "phase1-core-1.1",
    language: str = "en",
) -> dict[str, Any]:
    store = CertificationStore(db_path)
    scenario = {"subject": "HTTP Protocol Basics"}
    old_eval_config = {
        "rubric_version": "phase1-core-1.0",
        "perspectives": ["correctness", "pedagogy", "context"],
    }
    new_eval_config = {
        "rubric_version": new_rubric_version,
        "perspectives": ["correctness", "pedagogy", "context"],
    }
    report = await rejudge_episode(
        gateway=build_role_gateway(),
        store=store,
        source_episode_id=episode_id,
        scenario=scenario,
        new_evaluation_config=new_eval_config,
        old_evaluation_config=old_eval_config,
        new_rubric=next_rubric(new_rubric_version),
        language=language,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 evaluation-only change re-adjudication")
    parser.add_argument("--episode", required=True, help="source episode_id with the immutable 10-turn trace")
    parser.add_argument("--db", default="data/user/workspace/runtime/cert_phase1.db")
    parser.add_argument("--rubric-version", default="phase1-core-1.1")
    args = parser.parse_args()
    report = asyncio.run(
        run(
            episode_id=args.episode,
            db_path=args.db,
            new_rubric_version=args.rubric_version,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out_path = args.db.replace(".db", "_rejudge.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nreport -> {out_path}")


if __name__ == "__main__":
    main()
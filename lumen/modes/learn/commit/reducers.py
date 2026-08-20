"""Canonical reducers for the Learner Domain.

The commit service never trusts a caller-supplied mastery/qualitative snapshot.
Reducible derived state (``mastery_levels``, ``qualitative_mastery``) is
recomputed from the append-only evidence ledger; non-reducible state
(repetition, review, pending, modules, goal, …) is carried from the proposed
effect. On a version conflict the cursor / stage fields are protected so a
stale snapshot cannot advance them.

These reducers are deterministic and versioned (``REDUCER_VERSION``); bump the
version when the policy changes and re-project — never rewrite the ledger.
"""

from __future__ import annotations

from typing import Any

from lumen.modes.learn.domain.models import ErrorType, QuizAttempt
from lumen.modes.learn.policy.mastery import compute_mastery
from lumen.modes.learn.policy.policy import QUALITATIVE_TYPES

REDUCER_VERSION = "1"

# Evidence types that count as quantitative attempts for a knowledge point.
_ATTEMPT_LIKE = {"quiz_answer", "feynman_explanation", "review_answer"}
# Evidence types that drive the qualitative mastery gate directly (a Feynman
# explanation judgement). A wrong attempt on a qualitatively-gated KP also
# counts as a demotion signal (it contradicts a recorded pass).
_QUALITATIVE = {"feynman_explanation"}
_QUALITATIVE_TYPE_VALUES = {t.value for t in QUALITATIVE_TYPES}
# Non-reducible cursor/stage fields protected on conflict.
_PROTECTED_ON_CONFLICT = (
    "current_stage",
    "current_module_id",
    "current_kp_index",
)

_MAX_FAIL_DISPLAY = 0.4


def _outcome(row: dict[str, Any]) -> bool:
    outcome = row.get("outcome_json") or {}
    if "is_correct" in outcome:
        return bool(outcome["is_correct"])
    if "passed" in outcome:
        return bool(outcome["passed"])
    return bool(row.get("outcome"))


def _attempt_from_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a :class:`QuizAttempt` dict from a canonical evidence row.

    Every attempt in the authoritative ledger is representable as an attempt
    record so existing readers of ``progress.quiz_attempts`` keep working.
    """
    outcome = row.get("outcome_json") or {}
    raw = row.get("raw_response_json") or {}
    target_id = row.get("target_id") or ""
    error_type = outcome.get("error_type") or ""
    if row.get("evidence_type") == "feynman_explanation":
        error_type = "" if _outcome(row) else ErrorType.APPLICATION_ERROR.value
    return {
        "question_id": outcome.get("question_id") or "",
        "knowledge_point_id": target_id,
        "module_id": outcome.get("module_id") or "",
        "is_correct": _outcome(row),
        "user_answer": raw.get("user_answer") or "",
        "error_type": error_type or None,
        "self_attribution": outcome.get("self_attribution") or "",
        "question_kind": outcome.get("question_kind") or "recall",
        "misconception_node_id": outcome.get("misconception_node_id") or "",
        # Legacy fields present on a freshly built QuizAttempt.
        "mastery_estimate": 0.0,
        "timestamp": (row.get("observed_at_ms") or 0) / 1000.0,
    }


def _carry_source(base: dict[str, Any] | None, proposed: dict[str, Any], reconcile: bool) -> Any:
    """Field source on conflict = base (actual); on fast path = proposed."""
    if reconcile and base is not None:
        return base
    return proposed


def _recompute_mastery(ledger, base, proposed, reconcile):
    """Quantitative + qualitative mastery recomputed from the ledger.

    Only KPs with evidence are recomputed; evidence-less KPs keep the carry
    source value so imported / hand-set mastery is never erased.
    """
    knowledge_types = dict(proposed.get("knowledge_types") or {})
    if not knowledge_types and base is not None:
        knowledge_types = dict(base.get("knowledge_types") or {})

    # ordered attempt outcomes per kp, plus the latest qualitative-relevant
    # signal per kp (a Feynman judgement, or a wrong answer on a qualitative KP
    # which demotes a recorded pass).
    attempts: dict[str, list[bool]] = {}
    qual_signal_seq: dict[str, tuple[int, bool]] = {}
    for row in ledger:
        target = row.get("target_id") or ""
        row_type = row.get("evidence_type") or ""
        seq = int(row.get("evidence_seq", 0))
        if row_type in _ATTEMPT_LIKE:
            attempts.setdefault(target, []).append(_outcome(row))
        is_qual_kp = knowledge_types.get(target) in _QUALITATIVE_TYPE_VALUES
        if row_type in _QUALITATIVE:
            qual_signal_seq[target] = (seq, _outcome(row))
        elif row_type in _ATTEMPT_LIKE and is_qual_kp and not _outcome(row):
            # A wrong attempt against a qualitatively-gated KP contradicts a
            # previously recorded pass: demote the qualitative gate.
            qual_signal_seq[target] = (seq, False)

    carry = _carry_source(base, proposed, reconcile)
    mastery = dict(carry.get("mastery_levels") or {})
    qualitative = dict(carry.get("qualitative_mastery") or {})

    qual_order: dict[str, bool] = {}
    for target, (_seq, outcome) in qual_signal_seq.items():
        qual_order[target] = outcome

    # quantitative first — newest evidence weights matter.
    for target, correctness in attempts.items():
        mastery[target] = compute_mastery(correctness)
    # qualitative gate + display cap.
    for target, outcome in qual_order.items():
        qualitative[target] = outcome
        if outcome:
            mastery[target] = max(mastery.get(target, 0.0), 1.0)
        else:
            mastery[target] = min(mastery.get(target, 0.0), _MAX_FAIL_DISPLAY)
    return mastery, qualitative


def reduce_state(
    *,
    base: dict[str, Any] | None,
    proposed: dict[str, Any],
    ledger: list[dict[str, Any]],
    reconcile: bool,
) -> dict[str, Any]:
    """Combine a proposed effect with the canonical ledger into the next state.

    ``ledger`` is every valid evidence row for the learner in ``evidence_seq``
    order (already including this commit's new evidence).
    """
    result = dict(proposed)

    mastery, qualitative = _recompute_mastery(ledger, base, proposed, reconcile)
    result["mastery_levels"] = mastery
    result["qualitative_mastery"] = qualitative

    # quiz_attempts: canonical projection of all attempt-like evidence.
    attempts = [_attempt_from_evidence(row) for row in ledger]
    # Rebuild as Pydantic to keep serialisation / validation identical, but key
    # off evidence_seq so ordering is deterministic even if proposed reorders.
    attempts.sort(key=lambda a: a.get("timestamp", 0))
    result["quiz_attempts"] = attempts

    if reconcile and base is not None:
        for field in _PROTECTED_ON_CONFLICT:
            if field in base:
                result[field] = base[field]
    return result


def validate_attempt_evidence_shape(ledger: list[dict[str, Any]]) -> None:
    """Sanity helper for tests/migration: every attempt row can round-trip."""
    for row in ledger:
        try:
            QuizAttempt.model_validate(_attempt_from_evidence(row))
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"Evidence row {row.get('evidence_id')!r} is not reconstructable") from exc


__all__ = ["REDUCER_VERSION", "reduce_state", "validate_attempt_evidence_shape"]
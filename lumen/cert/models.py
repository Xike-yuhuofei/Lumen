"""Phase 1 Teaching Behavior Optimization Loop — data contract & shared enums.

Canonical home: ``lumen/cert``.

This module defines the frozen, auditable data concepts required by the Phase 1
Data Contract (``CandidateManifest`` / ``ContextManifest`` / ``Episode`` /
``TurnArtifact`` / ``EvaluationResult`` / ``FailureCase`` / ``RegressionCase``)
and the exact enum semantics the Certification State Machine relies on.

Raw Evaluator Verdict and Final Turn Status are *strictly separated* here:

    Raw:        GO | NO_GO
    Final:      PASS | FAIL | UNRESOLVED
    Eval init:  VALID | INVALID

These enums are the single source of truth for every plane (Teaching /
Evaluation / Control) and every gate in ``lumen.cert``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import enum
import hashlib
import json
import time
from typing import Any

# ── Enums ────────────────────────────────────────────────────────────────────


class RawVerdict(str, enum.Enum):
    """Raw per-evaluator verdict — only emitted on a VALID evaluation run."""

    GO = "GO"
    NO_GO = "NO_GO"


class EvaluationStatus(str, enum.Enum):
    """Executable-validity of an Evaluator run.

    ``VALID`` is the only status that may carry a decision. ``INVALID`` signals
    an execution-level problem (API failure / timeout / malformed output /
    missing input / model refusal) and forces ``decision = None``.
    """
    VALID = "VALID"
    INVALID = "INVALID"


class FinalTurnStatus(str, enum.Enum):
    """Final adjudicated status for a Turn after Failure Review.

    Only a *confirmed* ``LUMEN`` failure yields ``FAIL``; ``UNCERTAIN`` yields
    ``UNRESOLVED`` and may never be certified.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    UNRESOLVED = "UNRESOLVED"


class Attribution(str, enum.Enum):
    """Phase 1 fixed attribution set."""

    LUMEN = "LUMEN"
    EVALUATOR = "EVALUATOR"
    SIMULATOR = "SIMULATOR"
    RUBRIC = "RUBRIC"
    INFRA = "INFRA"
    UNCERTAIN = "UNCERTAIN"


class Phase1State(str, enum.Enum):
    """External Certification State Machine states (frozen in the Contract)."""

    EPISODE_INIT = "EPISODE_INIT"
    TURN_GENERATION = "TURN_GENERATION"
    TURN_EVALUATION = "TURN_EVALUATION"
    FAILURE_REVIEW = "FAILURE_REVIEW"
    FAILURE_ATTRIBUTION = "FAILURE_ATTRIBUTION"
    PATCHING = "PATCHING"  # Engineering Agent active (attribution = LUMEN only)
    FROZEN_REPLAY = "FROZEN_REPLAY"
    REGRESSION = "REGRESSION"
    CERTIFY = "CERTIFY"
    EPISODE_PASS = "EPISODE_PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class RegressionSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class EpisodeEnd(str, enum.Enum):
    NOT_DONE = "NOT_DONE"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


# ── Data concepts ────────────────────────────────────────────────────────────


def content_digest(data: Any) -> str:
    """Stable hex digest over a JSON-serialisable blob.

    Used to enforce the *no silent overwrite* rule: a CandidateManifest /
    ContextManifest carrying a different content digest than its id was issued
    under is rejected at write time.
    """
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CandidateManifest:
    """A frozen, versioned description of one Lumen tutor candidate.

    ``effective_candidate_id`` is the identity that must remain **identical**
    across an entire certification Episode. Any tutor-affecting change must
    produce a *new* id (never overwrite an old candidate).
    """
    effective_candidate_id: str
    parent_candidate_id: str | None
    content_digest: str
    tutor_config: dict[str, Any] = field(default_factory=dict)
    prompt_override: str = ""
    temperature: float = 0.2
    created_at: float = field(default_factory=time.time)
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextManifest:
    """Certification context identity — Trajectory + Evaluation separate.

    A change to the *trajectory* (learner utterance / learner state transition
    / tutor response / conversation history) invalidates the trajectory and
    forces restart from Turn 1. A change to how the immutable trace is *judged*
    is evaluation-only: the trace is kept but every turn is re-adjudicated with
    the one new EvaluationContext before certifying.
    """
    trajectory_context_id: str
    evaluation_context_id: str
    trajectory_digest: str
    evaluation_digest: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Episode:
    """One complete Turn 1..N teaching trajectory under one context set."""
    episode_id: str
    candidate_id: str
    trajectory_context_id: str
    evaluation_context_id: str
    status: EpisodeEnd = EpisodeEnd.NOT_DONE
    turn_count: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TurnArtifact:
    """An immutable single teaching turn.

    ``hidden_learner_state`` is the Learner Simulator's ground truth — never
    visible to the Tutor or the Evaluators. The Failure Reviewer MAY read it to
    diagnose the Simulator, but attribution must be based only on information
    Lumen was legitimately able to see.
    """
    episode_id: str
    turn_index: int  # 1-based
    learner_utterance: str
    tutor_action: str
    prior_conversation: list[dict[str, Any]] = field(default_factory=list)
    hidden_learner_state: dict[str, Any] = field(default_factory=dict)
    final_status: FinalTurnStatus | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvaluationResult:
    """One Evaluator run for one Turn.

    ``evaluation_status`` (VALID/INVALID) is separated from ``decision``
    (GO/NO_GO/None). Evidence must cite concrete teaching/dialogue evidence.
    """
    evaluation_id: str
    episode_id: str
    turn_index: int
    evaluator_id: str
    evaluator_perspective: str
    evaluation_status: EvaluationStatus
    decision: RawVerdict | None = None
    criterion_id: str = ""
    affected_turn: int = 0
    evidence: str = ""
    severity: str = ""
    reason: str = ""
    confidence: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FailureReview:
    """Failure Review + attribution for a NO_GO (or regression signal)."""
    failure_id: str
    episode_id: str
    turn_index: int
    non_go: list[EvaluationResult]
    attribution: Attribution
    reasoning: str
    reviewed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FailureCase:
    """A frozen confirmed-Lumen failure, replayable and sinkable to regression."""
    failure_case_id: str
    candidate_id: str
    criterion_id: str
    affected_turn: int
    frozen_checkpoint: dict[str, Any]  # fixed inputs for Frozen Replay
    status: str = "open"  # open | frozen | resolved
    regression_case_id: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RegressionCase:
    """An active regression case definition (never weakened/removed)."""
    regression_case_id: str
    description: str
    severity: RegressionSeverity
    checker: str  # register name of a deterministic checker in the regression runner
    data: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Audit: state transitions ────────────────────────────────────────────────


@dataclass(slots=True)
class TransitionLog:
    """Control-plane audit trail of Certification State Machine transitions."""
    transition_id: str
    episode_id: str
    from_state: Phase1State
    to_state: Phase1State
    reason: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "RawVerdict",
    "EvaluationStatus",
    "FinalTurnStatus",
    "Attribution",
    "Phase1State",
    "RegressionSeverity",
    "EpisodeEnd",
    "content_digest",
    "CandidateManifest",
    "ContextManifest",
    "Episode",
    "TurnArtifact",
    "EvaluationResult",
    "FailureReview",
    "FailureCase",
    "RegressionCase",
    "TransitionLog",
]
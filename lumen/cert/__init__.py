"""Phase 1 Teaching Behavior Optimization Loop.

Canonical home: ``lumen/cert``.

A bounded, isolatable, auditable certification loop that runs the **real Lumen
teaching path** (real mastery teaching prompt + real teaching policy + real
Lumen LLM) under one EffectiveCandidate, three Evaluator Perspectives, a
Learner Simulator, Failure Review / Attribution, and an Engineering Agent —
producing a 10-Turn Long-Horizon Teaching Stability Episode with 10 Final Turn
PASS when the candidate is accepted.

See :mod:`lumen.cert.engine` (CertificationController), the frozen state machine
in :mod:`lumen.cert.models` (Phase1State), and the data concepts
(CandidateManifest / ContextManifest / Episode / TurnArtifact / EvaluationResult
/ FailureCase / RegressionCase).

----
**STATUS: ``FROZEN BASELINE``** (Phase 1 Teaching Behavior Optimization Loop)

Frozen as the stable baseline for teaching-strategy experiments and Phase 2.
Scope is **Teaching Behavior Quality / Long-Horizon Teaching Stability only**
(10-Turn Certification with 10 Final Turn PASS under one EffectiveCandidate).
Learning Gain / Retention / Transfer / Mastery are explicitly **out of scope**.

Acceptance evidence (auditable):
* Real 10-Turn Certification PASS: ``data/user/workspace/runtime/cert_phase1_outcome.json``
  (+ ``cert_phase1.db`` trace: 3 candidate versions, 2 frozen LUMEN failures reconciled,
  final episode ``ep-143d...`` = 10/10 PASS under ``phase1-core-1.0``).
* Evaluation-only Change path (verified end-to-end):
  ``data/user/workspace/runtime/cert_phase1_rejudge.json`` — same immutable trace,
  new unified EvaluationContext(eval-35a5... / ``phase1-core-1.1``), 10 turns
  re-adjudicated, version relationship traceable.
* Deterministic machinery suite: ``lumen/cert/tests/test_cert.py`` (15 tests,
  incl. Evaluation-only Change re-adjudication).

Freeze rules (do not violate): keep the frozen State Machine / Data Contract /
Agent Permission Contract and the Teaching / Evaluation / Control Plane
isolation. Do not refactor or extend unless a genuinely blocking defect is
found, proven by a failing test, correctly attributed, fixed, and re-verified.
``FROZEN_BASELINE`` identifies this freeze in code.
"""

#: Phase 1 freeze marker — the certification loop is a reproducible frozen
#: baseline for teaching-behavior experiments and Phase 2. Change only on a
#: proven blocking defect (test → attribution → fix → regression).
FROZEN_BASELINE = "phase1-teaching-behavior-optimization-loop-v1.0-frozen"

from .engine import Budget, CertificationController, CertificationOutcome, build_contexts
from .models import (
    Attribution,
    CandidateManifest,
    ContextManifest,
    EpisodeEnd,
    EvaluationStatus,
    FinalTurnStatus,
    Phase1State,
    RawVerdict,
    RegressionSeverity,
    content_digest,
)

__all__ = [
    "CertificationController",
    "CertificationOutcome",
    "Budget",
    "build_contexts",
    "Attribution",
    "CandidateManifest",
    "ContextManifest",
    "EpisodeEnd",
    "EvaluationStatus",
    "FinalTurnStatus",
    "Phase1State",
    "RawVerdict",
    "RegressionSeverity",
    "content_digest",
    "FROZEN_BASELINE",
]
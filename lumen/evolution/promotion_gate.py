"""Promotion Gate v1 (Goal 7).

A candidate provider can never directly modify or overwrite the Production
Provider.  It progresses through a frozen, auditable pipeline; only a passing
Gate yields a promotion decision.  All transitions are appended to an audit
trail so promotions are auditable and rollback-able.

Pipeline::

    Candidate
      → static/contract validation
      → unit tests
      → regression tests
      → frozen benchmark
      → pareto evaluation
      → shadow test
      → A/B test
      → Promotion Gate
      → Production Provider
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any


class GateStage(str, Enum):
    STATIC_VALIDATION = "static_validation"
    UNIT_TESTS = "unit_tests"
    REGRESSION_TESTS = "regression_tests"
    FROZEN_BENCHMARK = "frozen_benchmark"
    PARETO_EVALUATION = "pareto_evaluation"
    SHADOW_TEST = "shadow_test"
    AB_TEST = "ab_test"
    PROMOTION = "promotion"


_STAGE_ORDER = [s for s in GateStage]


class GateDecision(str, Enum):
    PENDING = "pending"
    FAIL = "fail"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass
class GateCheck:
    """Outcome of one stage for a candidate."""

    stage: GateStage
    passed: bool
    detail: str = ""
    timestamp: float = field(default_factory=time.time)


class CandidateGate:
    """Frozen promotion lifecycle for a single candidate provider.

    ``judge`` is a pluggable callable ``(stage, candidate_id, context) -> bool``
    that returns whether the candidate clears that stage.  This keeps the gate
    policy separable from execution.
    """

    def __init__(self, candidate_id: str, judge: Any) -> None:
        self.candidate_id = candidate_id
        self._judge = judge
        self._results: dict[GateStage, GateCheck] = {}
        self.decision = GateDecision.PENDING
        self.audit_trail: list[dict[str, Any]] = []

    def _log(self, stage: GateStage, note: str) -> None:
        self.audit_trail.append(
            {
                "candidate": self.candidate_id,
                "stage": stage.value,
                "war_note": note,
                "ts": time.time(),
            }
        )

    def current_stage(self) -> GateStage:
        """Next unresolved stage, or PROMOTION when everything passed."""
        for s in _STAGE_ORDER:
            if s not in self._results:
                return s
        return GateStage.PROMOTION

    def _judge_safe(self, stage: GateStage, context: Any) -> bool:
        if callable(self._judge):
            return bool(self._judge(stage, self.candidate_id, context))
        # A dict/static policy: allow stage if its entry is truthy.
        if isinstance(self._judge, dict):
            return bool(self._judge.get(stage.value, self._judge.get(stage.name, False)))
        return False

    async def run(self, context: Any | None = None) -> GateDecision:
        """Run every stage in order; stop at the first failure.

        This NEVER touches production — it only returns a decision the caller
        may apply (via ``apply()``) if and only if PROMOTED.
        """
        for stage in _STAGE_ORDER:
            try:
                passed = self._judge_safe(stage, context)
            except Exception:  # noqa: BLE001
                passed = False
            check = GateCheck(stage=stage, passed=passed)
            self._results[stage] = check
            if passed:
                self._log(stage, "stage gate passed")
            else:
                self.decision = GateDecision.FAIL
                self._log(stage, "stage gate FAILED")
                return self.decision
        self.decision = GateDecision.PROMOTED
        self._log(GateStage.PROMOTION, "all stages passed; candidate cleared for promotion")
        return self.decision

    def apply(self) -> GateDecision:
        """The auditable promotion action.  Returns the decision.

        A promotion must be wired by the caller to a reversible binding that
        can later be rolled back — this harness never writes into production
        itself; it only produces the auditable decision.
        """
        return self.decision

    def rollback(self) -> GateDecision:
        self.decision = GateDecision.ROLLED_BACK
        self._log(GateStage.PROMOTION, "rollback recorded — production binding reverted")
        return self.decision

    def passed(self) -> bool:
        return self.decision == GateDecision.PROMOTED


class PromotionGate:
    """A registry of candidate gates + the immutable production provider id.

    The gate can never write to production; it only tracks candidates' audit
    trails and exposes promotion decisions for an external, reversible binding.
    """

    def __init__(self, production_provider_id: str) -> None:
        self.production_provider_id = production_provider_id
        self._candidates: dict[str, CandidateGate] = {}
        self.audit_trail: list[dict[str, Any]] = []

    def _log(self, entry: dict[str, Any]) -> None:
        self.audit_trail.append({**entry, "ts": time.time()})

    def register_candidate(self, candidate_id: str, judge: Any) -> CandidateGate:
        if candidate_id == self.production_provider_id:
            raise ValueError("a candidate may not be the production provider")
        gate = CandidateGate(candidate_id, judge)
        self._candidates[candidate_id] = gate
        self._log({"action": "register_candidate", "candidate": candidate_id})
        return gate

    def get(self, candidate_id: str) -> CandidateGate | None:
        return self._candidates.get(candidate_id)

    def evaluated(self) -> list[dict[str, Any]]:
        return [
            {"candidate": cid, "decision": g.decision.value, "trail": g.audit_trail}
            for cid, g in self._candidates.items()
        ]


__all__ = ["GateStage", "GateDecision", "GateCheck", "CandidateGate", "PromotionGate"]

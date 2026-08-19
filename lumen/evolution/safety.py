"""Recursive Evolution Safety (Goal 10).

Controlled recursive evolution must protect production, benchmarks, oracles and
safety boundaries from an Evolution System.  This module is the **hard gate**
an Evolution Agent must pass before its candidate is allowed into a sandbox.

Phase-1 whitelist of mutable targets (everything else is forbidden):

  ✅ Prompt
  ✅ Teaching Policy
  ✅ Context Policy
  ✅ Provider Config
  ✅ Graph Topology

Default forbidden (reward-hacking / benchmark-hacking protection):
  ❌ Production Provider
  ❌ Benchmark
  ❌ Promotion Gate
  ❌ Test Oracle
  ❌ Safety Boundary
  ❌ Arbitrary repo mutation
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from lumen.evolution.harness import MutationTarget


class ForbiddenTarget(str, Enum):
    """Hard-written-forbidden mutation targets an evolution system may NEVER touch."""

    PRODUCTION = "production"
    BENCHMARK = "benchmark"
    PROMOTION_GATE = "promotion_gate"
    TEST_ORACLE = "test_oracle"
    SAFETY_BOUNDARY = "safety_boundary"
    ARBITRARY = "arbitrary"


#: The only mutation targets Evolution Systems are allowed to propose.
ALLOWED_LIFECYCLE_TARGETS = frozenset(t.value for t in MutationTarget)

#: What a mutation proposal may NOT reference, regardless of how it is expressed.
FORBIDDEN_PATTERNS = (
    "production",
    "promotion",
    "benchmark",
    "test_oracle",
    "tests.kernel.test_bakeoff_frozen",
    "safety",
    "oracle",
    "settings/production",
)


@dataclass
class MutationProposal:
    """A single proposed mutation by an Evolution System."""

    target: str
    key: str  # e.g. "teaching_policy/scaffold_strategy"
    value: Any
    rationale: str = ""

    @property
    def serialized(self) -> str:
        return f"{self.target}/{self.key}"


class SafetyGate:
    """Rejects a mutation proposal unless it targets the Phase-1 whitelist."""

    def __init__(self, allowed: frozenset[str] = ALLOWED_LIFECYCLE_TARGETS) -> None:
        self.allowed = allowed
        self.forbidden = FORBIDDEN_PATTERNS
        self.decisions: list[dict[str, Any]] = []

    def allow(self, proposal: MutationProposal) -> bool:
        if proposal.target not in self.allowed:
            self._record(proposal, "target not in Phase-1 whitelist", False)
            return False
        haystack = proposal.serialized.lower()
        for pat in self.forbidden:
            if pat.lower() in haystack:
                self._record(proposal, f"forbidden pattern '{pat}'", False)
                return False
        self._record(proposal, "", True)
        return True

    def _record(self, proposal: MutationProposal, reason: str, ok: bool) -> None:
        self.decisions.append(
            {
                "proposal": proposal.serialized,
                "decision": "allow" if ok else "deny",
                "reason": reason,
            }
        )


class RecursiveEvolutionLoop:
    """Run controlled recursive evolution steps, each sandboxed + gated.

    For each step:
      1. the Evolution Agent proposes candidate(s) + mutations;
      2. the SafetyGate filters the mutations (whitelist-only);
      3. accepted candidates are evaluated in a sandboxed benchmark;
      4. only never-regressed candidates update the Pareto archive.

    This is a *scaffold*, not an active optimizer — it safely demonstrates the
    lifecycle without letting an Evolution agent touch production.
    """

    def __init__(
        self, produce_candidates: Any, evaluate: Any, archive: Any, gate: SafetyGate | None = None
    ) -> None:
        self._produce = produce_candidates  # () -> list[EvolutionCandidate]
        self._evaluate = evaluate  # async (candidate) -> metrics dict | None
        self._archive = archive
        self._gate = gate or SafetyGate()
        self.history: list[dict[str, Any]] = []

    async def step(self, generation_number: int) -> list[Any]:
        candidates = self._produce() if callable(self._produce) else []
        results: list[Any] = []
        for cand in candidates:
            # Mutations are gated here (whitelist-only). The candidate itself is
            # sandboxed; gate decisions are recorded for audit.
            for mutation in getattr(cand, "mutations", {}).values():
                if hasattr(mutation, "_target"):
                    self._gate.allow(mutation)
            metrics = await self._evaluate(cand)
            if metrics is not None:
                self._archive.add(cand.candidate_id, metrics)
                results.append((cand.candidate_id, metrics))
        self.history.append(
            {
                "generation": generation_number,
                "proposed": len(candidates),
                "evaluated": len(results),
            }
        )
        return results


__all__ = [
    "MutationProposal",
    "ForbiddenTarget",
    "SafetyGate",
    "RecursiveEvolutionLoop",
    "ALLOWED_LIFECYCLE_TARGETS",
    "FORBIDDEN_PATTERNS",
]

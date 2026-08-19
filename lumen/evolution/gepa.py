"""GEPA integration design (Goal 9).

This is a feasibility study + minimal adapter **contract** — NOT a production
integration.  It answers whether and how a future Evolution System (GEPA /
EvoAgentX / AFlow / DSPy / DGM / self-hosted) can evolve Lumen's Agent Runtime.

It is a pure-contract module: importing it does not depend on GEPA or on Lumen's
core, and it does NOT modify any Lumen core architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lumen.evolution.harness import MutationTarget

# ── Where GEPA-style evolution can act ────────────────────────────────────
#
# Per the Phase-1 whitelist, an Evolution System may propose new values for:
#   prompt, teaching_policy, context_policy, provider_config, graph_topology
# Each maps to a mutation the SafetyGate must still approve before sandboxing.


@dataclass
class EvolutionObjective:
    """A fitness direction for the Evolution System (Pareto-multi-objective)."""

    name: str
    metric_key: str  # e.g. rt_output_quality
    higher_is_better: bool = True


@dataclass
class EvolutionResult:
    """Returned to the Evolution System after evaluating one candidate."""

    candidate_id: str
    fitness: dict[str, float]  # per-objective scores (NOT a single fused score)
    passed: bool = False
    detail: str = ""


class GepaAdapter(Protocol):
    """The recommended Lumen ↔ GEPA Adapter Contract.

    An Evolution System routes all of its candidate mutation + evaluation
    through these three calls, so Lumen keeps full control of the sandbox,
    regression, benchmark, pareto archive, and promotion gate.
    """

    def map_whitelist(self) -> list[MutationTarget]: ...

    def evaluate(self, candidate: Any) -> EvolutionResult: ...

    def promote(self, candidate_id: str) -> str: ...


@dataclass
class GepaFeasibility:
    """Static findings of the GEPA feasibility study (recorded, not runtime)."""

    integration_points: list[str] = field(
        default_factory=lambda: [
            "prompt",  # evolve system/user prompt text for teaching clarity
            "teaching_policy",  # evolve scaffold / remediation / assessment strategy params
            "context_policy",  # evolve how KB/memory seeds are weighted/selected
            "provider_config",  # evolve model/tool wiring params of a provider
            "graph_topology",  # evolve LangGraph node order / branching
        ]
    )
    hard_blockers: list[str] = field(
        default_factory=lambda: [
            # GEPA must NOT drive: production binding, benchmark definition, gate logic,
            # test oracles, or arbitrary repo edits.  See lumen.evolution.safety.
        ]
    )
    recommended_contract: str = "adapters.GepaAdapter + SafetyGate + ParetoArchive + PromotionGate"
    verdict: str = (
        "FEASIBLE for harness-level PoC; NOT recommended for production now. "
        "GEPA's evolutionary search fits the whitelist (prompt / teaching_policy / "
        "context_policy / provider_config / graph_topology), but must be contained by "
        "the SafetyGate and evaluated only through the sandboxed benchmark."
    )


def feasibility() -> GepaFeasibility:
    """Return the recorded feasibility findings."""
    return GepaFeasibility()


__all__ = [
    "EvolutionObjective",
    "EvolutionResult",
    "GepaAdapter",
    "GepaFeasibility",
    "feasibility",
]

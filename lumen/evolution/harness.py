"""Evolution Harness core objects & interfaces (Goal 8).

Defines the primitives a future Evolution System (GEPA / EvoAgentX / AFlow /
DSPy / DGM / self-hosted Evolution Agent) will operate on.  Phase 1 only builds
the interfaces and the harness — it does NOT include an active evolution loop.

Evolution Systems are restricted to a Phase-1 whitelist of mutation targets and
are HARD-BLOCKED from mutating Production, the Benchmark, the Promotion Gate,
test oracles, and safety boundaries (see :mod:`lumen.evolution.safety` and
:mod:`lumen.evolution.goal10`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from lumen.evolution.record import ExperimentRecord

T = TypeVar("T")


class MutationTarget(str, Enum):
    """The ONLY things Phase-1 Evolution Systems may mutate."""

    PROMPT = "prompt"
    TEACHING_POLICY = "teaching_policy"
    CONTEXT_POLICY = "context_policy"
    PROVIDER_CONFIG = "provider_config"
    GRAPH_TOPOLOGY = "graph_topology"


@dataclass
class EvolutionCandidate:
    """A candidate provider configuration (or code unit) under evolution."""

    candidate_id: str
    parent_id: str | None = None
    base_provider_id: str = "legacy"
    mutations: dict[MutationTarget, Any] = field(default_factory=dict)
    lineage: list[str] = field(default_factory=list)
    generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


EvaluationT = TypeVar("EvaluationT")


@dataclass
class EvaluationResult(Generic[T]):
    """Outcome of evaluating one candidate on one benchmark scenario."""

    candidate_id: str
    scenario_id: str
    provider_id: str
    ok: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    detail: str = ""


@dataclass
class ExecutionTrace:
    """Full observable run log for a candidate (provenance + audit)."""

    candidate_id: str
    events: list[Any] = field(default_factory=list)

    def append(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class Experiment:
    """One controlled experiment run (scenario × provider × rep)."""

    experiment_id: str
    provider_id: str
    benchmark_version: str
    seed: int | None = None
    records: list[ExperimentRecord] = field(default_factory=list)
    groups: dict[str, list[Any]] = field(default_factory=dict)  # e.g. control/replica


@dataclass
class Generation:
    """One generation of candidates produced by an Evolution System."""

    number: int
    candidates: list[EvolutionCandidate] = field(default_factory=list)
    evaluations: list[EvaluationResult[Any]] = field(default_factory=list)
    parent_lineage: list[str] = field(default_factory=list)

    def best(self, order: Any | None = None) -> EvolutionCandidate | None:
        if not self.candidates:
            return None
        if order is None:
            return self.candidates[0]
        scored = [(order(c), c) for c in self.candidates]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]


@dataclass
class PromotionDecision:
    """The auditable output of the Promotion Gate for a candidate."""

    candidate_id: str
    decision: str  # pending / fail / promoted / rolled_back
    stage: str = ""
    audit_trail: list[dict[str, Any]] = field(default_factory=list)
    record: ExperimentRecord | None = None


class EvolutionHarness:
    """The top-level harness facade.

    Composes benchmark, pareto archive, promotion gate, and experiment lineage.
    It does NOT implement selection/evolution logic — evolution systems consume
    these primitives.
    """

    def __init__(self, benchmark: Any, target_provider_ids: list[str] | None = None) -> None:
        self._benchmark = benchmark
        self._target_provider_ids = target_provider_ids or []
        self._archive: Any = None
        self._promotion_gate: Any = None
        self._experiments: list[Experiment] = []

    def set_archive(self, archive: Any) -> "EvolutionHarness":
        self._archive = archive
        return self

    def set_promotion_gate(self, gate: Any) -> "EvolutionHarness":
        self._promotion_gate = gate
        return self

    async def evaluate(self, run: Any) -> list[EvaluationResult[Any]]:
        """Run the benchmark and map results onto EvaluationResults."""
        results: list[EvaluationResult[Any]] = []
        for report in run.reports:
            ok = bool(report.metrics.runtime.task_success)
            results.append(
                EvaluationResult[Any](
                    candidate_id=report.provider_id,
                    scenario_id=report.scenario_id,
                    provider_id=report.provider_id,
                    ok=ok,
                    metrics=report.metrics.as_dict(),
                )
            )
        return results

    def record_experiment(self, experiment_id: str, records: list[ExperimentRecord], seed: int | None) -> Experiment:
        exp = Experiment(
            experiment_id=experiment_id,
            provider_id=",".join(self._target_provider_ids),
            benchmark_version="v2",
            seed=seed,
            records=records,
        )
        self._experiments.append(exp)
        return exp

    def experiments(self) -> list[Experiment]:
        return list(self._experiments)


__all__ = [
    "MutationTarget",
    "EvolutionCandidate",
    "EvaluationResult",
    "ExecutionTrace",
    "Experiment",
    "Generation",
    "PromotionDecision",
    "EvolutionHarness",
]
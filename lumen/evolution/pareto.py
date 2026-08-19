"""Pareto evaluation & archive (Goal 6).

Providers are compared on separate axes — never a weighted single score.  A
provider dominates another when it is >= on every axis (with all axes oriented
so *higher is better*) and strictly better on at least one.  The Pareto archive
keeps every non-dominated provider as a viable candidate.

Axes used (each a float, higher = better):
  Quality↑   = rt_output_quality
  Teaching↑  = teach_teaching_effect  (aggregate teaching correctness / effect)
  Reliability↑ = rt_task_success (or 1 - failure_rate)
  Cost↓      = inverted rt_token_usage / step_count (fewer = better)
  Latency↓   = inverted rt_latency (faster = better)
  Complexity↓ = inverted step_count (simpler loop = better)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AxisSpec:
    """One evaluation axis: a metric key and its orientation."""

    name: str
    key: str  # metric dict key
    higher_is_better: bool = True
    weight: float = 1.0  # informational — NOT used to form a single weighted score


DEFAULT_AXES: list[AxisSpec] = [
    AxisSpec("quality", "rt_output_quality", True),
    AxisSpec("teaching", "teach_teaching_effect", True),
    AxisSpec("reliability", "rt_task_success", True),
    AxisSpec("cost", "rt_step_count", False),  # fewer steps = better (cost ↓)
    AxisSpec("latency", "rt_latency", False),
    AxisSpec("complexity", "rt_step_count", False),
]


def _value(metrics: dict[str, float], key: str) -> float:
    return float(metrics.get(key, 0.0))


def dominates(
    a: dict[str, float],
    b: dict[str, float],
    axes: list[AxisSpec] | None = None,
) -> bool:
    """True if candidate *a* Pareto-dominates candidate *b* on the given axes."""
    axes = axes or DEFAULT_AXES
    better_any = False
    for ax in axes:
        va, vb = _value(a, ax.key), _value(b, ax.key)
        if ax.higher_is_better:
            if va < vb:
                return False
            if va > vb:
                better_any = True
        else:
            if va > vb:
                return False
            if va < vb:
                better_any = True
    return better_any  # equal on all axes → not dominating


def pareto_frontier(
    candidates: list[dict[str, float]],
    axes: list[AxisSpec] | None = None,
) -> list[dict[str, float]]:
    """Return the subset of candidates not dominated by any other candidate."""
    front: list[dict[str, float]] = []
    for cand in candidates:
        dominated = any(dominates(other, cand, axes) for other in candidates)
        if not dominated:
            front.append(cand)
    return front


@dataclass
class ParetoCandidate:
    """A named candidate in the archive, with its per-axis scores."""

    provider_id: str
    metrics: dict[str, float]
    axis_values: dict[str, float] = field(default_factory=dict)

    def dominated_by(self, other: "ParetoCandidate", axes: list[AxisSpec] | None = None) -> bool:
        return dominates(other.metrics, self.metrics, axes)


class ParetoArchive:
    """Keeps every non-dominated provider as a viable Pareto-optimal solution."""

    def __init__(self, axes: list[AxisSpec] | None = None) -> None:
        self.axes = axes or DEFAULT_AXES
        self._candidates: dict[str, ParetoCandidate] = {}

    def add(self, provider_id: str, metrics: dict[str, float]) -> None:
        cand = ParetoCandidate(provider_id=provider_id, metrics=dict(metrics))
        cand.axis_values = {ax.name: _value(metrics, ax.key) for ax in self.axes}
        # Drop the new candidate if any existing member dominates it.
        if any(cand.dominated_by(member, self.axes) for member in self._candidates.values()):
            return
        # Evict existing members dominated by the new candidate, then insert.
        self._candidates = {
            pid: m for pid, m in self._candidates.items() if not m.dominated_by(cand, self.axes)
        }
        self._candidates[provider_id] = cand

    def members(self) -> list[ParetoCandidate]:
        return list(self._candidates.values())

    def provider_ids(self) -> list[str]:
        return sorted(self._candidates.keys())

    def summary(self) -> dict[str, Any]:
        return {
            "frontier": self.provider_ids(),
            "n_members": len(self._candidates),
            "axes": [a.name for a in self.axes],
        }


__all__ = ["AxisSpec", "DEFAULT_AXES", "dominates", "pareto_frontier", "ParetoCandidate", "ParetoArchive"]
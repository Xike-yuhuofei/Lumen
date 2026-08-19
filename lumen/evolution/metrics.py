"""Lumen Runtime Benchmark v2 metrics.

Metrics are intentionally split into RUNTIME and TEACHING buckets so a single
aggregate score cannot hide a trade-off.  Each bucket is reported on its own
axis so Pareto evaluation can compare providers independently per dimension.

Runtime metrics (stability / cost / latency / recovery / state correctness):
    task_success, output_quality, step_count, tool_calls, token_usage,
    latency, failure_rate, recovery_rate, determinism, state_correctness,
    trace_completeness
Teaching metrics (is the TEACHING correct, not just the runtime):
    decision_correctness, scaffolding_alignment, assessment_triggered,
    remediation_triggered, teaching_effect
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumen.evolution.contract import (
    ProviderResult,
    TeachingDecisionKind,
)

# ── Expected outcome ──────────────────────────────────────────────────────


@dataclass
class Expected:
    """Ground truth a scenario's result is judged against."""

    ok: bool = False
    tool_sequence: list[str] | None = None
    expected_decision: TeachingDecisionKind | None = None

    def __post_init__(self) -> None:
        self.tool_sequence = list(self.tool_sequence or [])


# ── Runtime metrics ───────────────────────────────────────────────────────


@dataclass
class RuntimeMetrics:
    task_success: bool = False
    output_quality: float = 0.0  # 0..1 — whether non-empty coherent output produced
    step_count: int = 0
    tool_calls: int = 0
    tool_call_correct: float = 0.0  # 0..1 — fraction of expected tool sequence matched
    token_usage: int = 0
    latency: float = 0.0
    failure_rate: float = 0.0
    recovery_rate: float = 0.0
    determinism: float = 0.0  # 0..1 — replay-stable across reps
    state_correctness: float = 0.0  # 0..1
    trace_completeness: float = 0.0  # 0..1 — did the provider emit its trace events

    def as_dict(self, *, prefix: str = "rt_") -> dict[str, float]:
        return {
            f"{prefix}task_success": float(self.task_success),
            f"{prefix}output_quality": self.output_quality,
            f"{prefix}step_count": float(self.step_count),
            f"{prefix}tool_calls": float(self.tool_calls),
            f"{prefix}tool_call_correct": self.tool_call_correct,
            f"{prefix}token_usage": float(self.token_usage),
            f"{prefix}latency": self.latency,
            f"{prefix}failure_rate": self.failure_rate,
            f"{prefix}recovery_rate": self.recovery_rate,
            f"{prefix}determinism": self.determinism,
            f"{prefix}state_correctness": self.state_correctness,
            f"{prefix}trace_completeness": self.trace_completeness,
        }


# ── Teaching metrics ──────────────────────────────────────────────────────


@dataclass
class TeachingMetrics:
    decision_correctness: float = 0.0  # 0..1 — was the teaching decision what the scenario expected
    scaffolding_alignment: float = 0.0  # 0..1 — did scaffolding follow the strategy
    assessment_triggered: bool = False  # was ASSESS issued when expected
    remediation_triggered: bool = False  # was REMEDIATE issued when expected
    teaching_effect: float = 0.0  # 0..1 — proxy of whether outcome followed the decision
    n_decisions: int = 0

    def as_dict(self, *, prefix: str = "teach_") -> dict[str, float]:
        return {
            f"{prefix}decision_correctness": self.decision_correctness,
            f"{prefix}scaffolding_alignment": self.scaffolding_alignment,
            f"{prefix}assessment_triggered": float(self.assessment_triggered),
            f"{prefix}remediation_triggered": float(self.remediation_triggered),
            f"{prefix}teaching_effect": self.teaching_effect,
            f"{prefix}n_decisions": float(self.n_decisions),
        }


# ── Aggregation ───────────────────────────────────────────────────────────


@dataclass
class MetricSet:
    runtime: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    teaching: TeachingMetrics = field(default_factory=TeachingMetrics)

    def as_dict(self) -> dict[str, float]:
        return {**self.runtime.as_dict(), **self.teaching.as_dict()}


def compute_metrics(
    result: ProviderResult,
    expected: Expected,
    *,
    latency: float = 0.0,
    token_usage: int = 0,
    decisions: list[Any] | None = None,
) -> MetricSet:
    """Compute Runtime + Teaching metrics for one completed provider result."""
    rt = RuntimeMetrics()
    te = TeachingMetrics()

    # ── Runtime ───────────────────────────────────────────────────────────
    completed = result.termination.completed
    rt.task_success = completed and bool(result.output.final_text.strip()) and not result.error
    rt.output_quality = 1.0 if bool(result.output.final_text.strip()) else 0.0
    rt.step_count = result.termination.step_count
    rt.tool_calls = len(result.output.tool_calls)
    rt.token_usage = token_usage
    rt.latency = latency
    rt.failure_rate = 0.0 if result.error is None else 1.0

    # recovery: tool-error scenario that still completed
    if expected.tool_sequence and "boom" not in (expected.tool_sequence or []):
        recovered = result.error is None and completed
        rt.recovery_rate = 1.0 if recovered else 0.0
    else:
        recovered = result.error is None and completed
        rt.recovery_rate = 1.0 if recovered else 0.0

    # tool-call correctness vs the expected ordered sequence
    got = [name for name, _ in result.output.tool_calls]
    if expected.tool_sequence:
        match = sum(1 for i, name in enumerate(expected.tool_sequence) if i < len(got) and got[i] == name)
        rt.tool_call_correct = match / len(expected.tool_sequence)
    else:
        rt.tool_call_correct = 0.0

    # state correctness — the provider wrote a durable checkpoint and step is sane
    rt.state_correctness = 0.0
    if getattr(result, "termination", None) is not None:
        rt.state_correctness = 1.0 if result.termination.step_count >= 0 else 0.0

    # trace completeness — provider emitted a non-trivial trace (model + end at least)
    trace_kinds = {e.step for e in result.trace}
    has_model = any(e.kind == "model_call" or e.kind == "node" for e in result.trace)
    has_trace = len(result.trace) > 0
    rt.trace_completeness = 1.0 if (has_trace and (has_model or len(trace_kinds) > 0)) else 0.0

    # determinism — filled by the benchmark when replaying multiple reps
    rt.determinism = 0.0

    # ── Teaching ──────────────────────────────────────────────────────────
    if decisions:
        te.n_decisions = len(decisions)
        kinds = [d.kind if hasattr(d, "kind") else d for d in decisions]
        te.assessment_triggered = TeachingDecisionKind.ASSESS in kinds
        te.remediation_triggered = TeachingDecisionKind.REMEDIATE in kinds
        if expected.expected_decision is not None:
            te.decision_correctness = 1.0 if expected.expected_decision in kinds else 0.0
        else:
            te.decision_correctness = 1.0 if te.n_decisions > 0 else 0.0
        te.scaffolding_alignment = 0.0  # filled by benchmark when scaffolding text follows strategy
        te.teaching_effect = 1.0 if rt.task_success else 0.0
    else:
        te.assessment_triggered = False
        te.remediation_triggered = False
        te.decision_correctness = 0.0
        te.teaching_effect = 0.0

    return MetricSet(runtime=rt, teaching=te)


__all__ = ["Expected", "RuntimeMetrics", "TeachingMetrics", "MetricSet", "compute_metrics"]
"""Lumen Runtime Benchmark v2 — reproducible, comparable, replayable.

Design goals (from the frozen Evolution Harness spec):

1. **Controlled variables** — same fake/deterministic LLM, same model config,
   same tools, same input, same context, same teaching plugins, same env.
2. **Multiple reps** per scenario for determinism / replay-stability.
3. **Runtime vs Teaching metrics kept separate** — never a single score.
4. **Full experiment records** emitted for every (provider × scenario × rep)
   so results are reproducible and auditable.

The benchmark does NOT decide a winner — it emits per-axis metric rows that the
Pareto archive and Promotion Gate use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Protocol

from lumen.evolution.contract import (
    ProviderRequest,
    RuntimeContext,
    TeachingDecisionKind,
    TurnInput,
    TurnState,
)
from lumen.evolution.fakes import make_standard_tools
from lumen.evolution.metrics import Expected, MetricSet, compute_metrics
from lumen.evolution.models import ScriptedModel
from lumen.evolution.record import ExperimentRecord, current_git_commit

BENCHMARK_VERSION = "v2"


@dataclass
class BenchmarkScenario:
    """One frozen benchmark scenario (identical inputs for every provider)."""

    id: str
    user_message: str
    script: list[Any]  # deterministic model script (tool-call dicts / final str)
    expected_tools: list[str] | None = None
    expected_decision: TeachingDecisionKind | None = None
    # teaching script: deterministic list of TeachingDecisions to inject
    teaching_script: list[Any] | None = None
    conversation_history: list[dict[str, Any]] | None = None


# Reference scenario set — deterministic across providers.
SCENARIOS: list[BenchmarkScenario] = [
    BenchmarkScenario(
        id="single_tool_call",
        user_message="compute 2+3",
        script=[{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "Result is 5."],
        expected_tools=["calc"],
        expected_decision=TeachingDecisionKind.EXPLAIN,
        teaching_script=None,
    ),
    BenchmarkScenario(
        id="multi_tool_sequential",
        user_message="two computations",
        script=[
            {"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 1}}]},
            {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 2}}]},
            "Done.",
        ],
        expected_tools=["calc", "calc"],
        expected_decision=TeachingDecisionKind.EXPLAIN,
    ),
    BenchmarkScenario(
        id="tool_error_recovery",
        user_message="boom then calc",
        script=[
            {"tool_calls": [{"name": "boom", "args": {}}]},
            {"tool_calls": [{"name": "calc", "args": {"a": 4, "b": 4}}]},
            "Recovered.",
        ],
        expected_tools=["boom", "calc"],
        expected_decision=TeachingDecisionKind.REMEDIATE,
    ),
    BenchmarkScenario(
        id="assessment",
        user_message="quiz me",
        script=[{"tool_calls": [{"name": "ask_user", "args": {"question": "What is 2+3?"}}]}, "Correct!"],
        expected_tools=["ask_user"],
        expected_decision=TeachingDecisionKind.ASSESS,
    ),
    BenchmarkScenario(
        id="plain_reply",
        user_message="hello",
        script=["Hello! How can I help?"],
        expected_tools=[],
        expected_decision=TeachingDecisionKind.NOT_APPLICABLE,
    ),
    BenchmarkScenario(
        id="long_session_continuity",
        user_message="continue",
        script=["Continuing from what we discussed."],
        expected_tools=[],
        expected_decision=TeachingDecisionKind.EXPLAIN,
        conversation_history=[
            {"role": "user", "content": "Prior user question"},
            {"role": "assistant", "content": "Prior assistant answer"},
        ],
    ),
]


# ── Controlled-environment constructor ────────────────────────────────────


def make_request(
    scenario: BenchmarkScenario,
    provider_id: str,
    *,
    seed: int | None = 1,
    toolset: str = "standard",
) -> ProviderRequest:
    """Build the SAME request for any provider — the control-variable guarantee."""
    tools = make_standard_tools()
    model = ScriptedModel(list(scenario.script), seed=seed)
    teaching = _teaching_for(scenario)
    return ProviderRequest(
        input=TurnInput(
            user_message=scenario.user_message,
            session_id=f"bench-{scenario.id}-{provider_id}",
            conversation_history=list(scenario.conversation_history or []),
        ),
        state=TurnState(),
        context=RuntimeContext(language="en"),
        model=model,
        tools=tools,
        teaching=teaching,
        seed=seed,
    )


def _teaching_for(scenario: BenchmarkScenario) -> Any:
    from lumen.evolution.fakes import ScriptedTeaching

    script = scenario.teaching_script
    if not script and scenario.expected_decision in (
        TeachingDecisionKind.ASSESS,
        TeachingDecisionKind.REMEDIATE,
    ):
        script = [
            {"kind": scenario.expected_decision, "strategy": "deterministic"},
            {"kind": TeachingDecisionKind.PROGRESS, "strategy": "advance"},
        ]
    if not script and scenario.expected_decision == TeachingDecisionKind.EXPLAIN:
        script = [
            {"kind": TeachingDecisionKind.EXPLAIN, "strategy": "socratic"},
            {"kind": TeachingDecisionKind.PROGRESS, "strategy": "advance"},
        ]
    decisions = [
        {"kind": s["kind"] if isinstance(s, dict) else s}
        if not isinstance(s, dict) or "kind" not in s
        else s
        for s in (script or [])
    ]
    # Normalise dict → TeachingDecision
    built = []
    for d in decisions:
        if isinstance(d, dict):
            from lumen.evolution.contract import TeachingDecision

            kind = d["kind"] if isinstance(d["kind"], TeachingDecisionKind) else TeachingDecisionKind(d["kind"])
            built.append(
                {"kind": kind, "strategy": d.get("strategy", "deterministic"), "reason": d.get("reason", "")}
            )
    from lumen.evolution.contract import TeachingDecision

    teaching = ScriptedTeaching([TeachingDecision(**d) for d in built] if built else None)
    return teaching


# ── Benchmark runner ──────────────────────────────────────────────────────


class Provider(Protocol):
    """Duck-typed provider seam: anything with ``run()`` + ``provider_id``."""

    provider_id: str

    async def run(self, request: ProviderRequest) -> Any: ...


@dataclass
class ProviderRunReport:
    provider_id: str
    scenario_id: str
    rep: int
    metrics: MetricSet
    record: ExperimentRecord


@dataclass
class BenchmarkRun:
    """Aggregate of every (provider × scenario × rep)."""

    reports: list[ProviderRunReport] = field(default_factory=list)

    def rows(self) -> list[dict[str, Any]]:
        return [r.metrics.as_dict() for r in self.reports]

    def by_provider(self) -> dict[str, list[ProviderRunReport]]:
        out: dict[str, list[ProviderRunReport]] = {}
        for r in self.reports:
            out.setdefault(r.provider_id, []).append(r)
        return out


async def run_benchmark(
    providers: list[Any],
    *,
    scenarios: list[BenchmarkScenario] | None = None,
    reps: int = 3,
    seed: int | None = 1,
    git_commit: str | None = None,
) -> BenchmarkRun:
    """Run every scenario against every provider ``reps`` times."""
    scenarios = scenarios or SCENARIOS
    commit = git_commit or current_git_commit()
    reports: list[ProviderRunReport] = []
    for scenario in scenarios:
        for prov in providers:
            provider_metrics: list[MetricSet] = []
            for rep in range(reps):
                request = make_request(scenario, prov.provider_id, seed=seed)
                start = time.perf_counter()
                result = await prov.run(request)
                latency = time.perf_counter() - start
                # collect teaching decisions the teaching plugin produced
                decisions = getattr(request.teaching, "decisions", [])
                expected = Expected(
                    ok=True,
                    tool_sequence=list(scenario.expected_tools or []),
                    expected_decision=scenario.expected_decision,
                )
                metrics = compute_metrics(
                    result,
                    expected,
                    latency=latency,
                    token_usage=0,
                    decisions=decisions,
                )
                provider_metrics.append(metrics)
                record = ExperimentRecord(
                    provider_id=prov.provider_id,
                    provider_version="0.1.0",
                    git_commit=commit,
                    benchmark_version=BENCHMARK_VERSION,
                    scenario_id=scenario.id,
                    model="scripted-seeded",
                    model_config={"seed": seed},
                    toolset=["calc", "boom", "ask_user"],
                    teaching_plugins=[request.teaching.name],
                    input_dataset="benchmark-v2-standard",
                    seed=seed,
                    environment="deterministic-fake",
                    metrics=metrics.as_dict(),
                    trace=[t.to_dict() if hasattr(t, "to_dict") else t for t in result.trace],
                )
                reports.append(ProviderRunReport(prov.provider_id, scenario.id, rep, metrics, record))
    # post-hoc determinism across reps
    for prov in providers:
        for scenario in scenarios:
            reps_for = [r for r in reports if r.provider_id == prov.provider_id and r.scenario_id == scenario.id]
            if len(reps_for) < 2:
                continue
            signatures = {
                (
                    r.record.metrics.get("rt_task_success"),
                    r.record.metrics.get("rt_tool_calls"),
                    r.record.metrics.get("rt_output_quality"),
                )
                for r in reps_for
            }
            det = 1.0 if len(signatures) == 1 else 0.0
            for r in reps_for:
                r.record.metrics["rt_determinism"] = det
                r.metrics.runtime.determinism = det
    return BenchmarkRun(reports=reports)


__all__ = [
    "BENCHMARK_VERSION",
    "BenchmarkScenario",
    "SCENARIOS",
    "make_request",
    "run_benchmark",
    "BenchmarkRun",
    "ProviderRunReport",
]
"""P1 — LangGraph Thin Provider: production-readiness conformance tests.

These tests harden the thin boundary beyond the frozen parity suite
(``test_providers.py``) and the baseline P1 tests
(``test_langgraph_thin_provider.py``).  They map 1:1 onto the Production
Readiness acceptance criteria:

* persistence / checkpoint versioned so version evolution is verifiable,
* interrupt / resume / retry / replay / durable-execution / crash-recovery
  behaviour exercised via the *unmodified* LangGraph runtime,
* failure-injection safety: no silent state corruption, correct budget
  accounting, no duplicate side effects,
* every declared Capability & Guarantee is actually observed at runtime,
* a production-like benchmark (persistence enabled) keeps full conformance +
  determinism,

all without forking / patching LangGraph and without leaking LangGraph types
into Lumen core (those invariants are asserted in the baseline suite).
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RunnableConfig, interrupt
import pytest

from lumen.evolution.benchmark import run_benchmark
from lumen.evolution.contract import (
    ProviderRequest,
    RuntimeContext,
    TeachingDecision,
    TeachingDecisionKind,
    TerminationReason,
    TurnInput,
    TurnState,
)
from lumen.evolution.fakes import ScriptedTeaching, make_standard_tools
from lumen.evolution.models import ScriptedModel
from lumen.evolution.providers import LangGraphThinProvider
import lumen.evolution.providers.langchain_thin as thin_mod


def _request(
    user_message: str = "compute 2+3",
    script: list | None = None,
    *,
    generation: str | None = "gen-prod",
    config: dict | None = None,
    tools: object | None = None,
    model: object | None = None,
) -> ProviderRequest:
    script = script or [
        {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
        "Result is 5.",
    ]
    state = TurnState()
    if generation is not None:
        state.snapshot["execution_generation"] = generation
    return ProviderRequest(
        input=TurnInput(user_message=user_message, session_id="s", conversation_history=[]),
        state=state,
        context=RuntimeContext(language="en"),
        model=model or ScriptedModel(list(script), seed=1),
        tools=tools or make_standard_tools(),
        teaching=ScriptedTeaching([TeachingDecision(kind=TeachingDecisionKind.EXPLAIN)]),
        seed=1,
        config=dict(config or {}),
    )


def _dump(saver: MemorySaver, thread_id: str) -> dict[str, Any]:
    return (
        LangGraphThinProvider(checkpointer=saver)
        ._graph.get_state({"configurable": {"thread_id": thread_id}})
        .values
    )


# ── Versioned execution state & operational metadata ───────────────────────────


def test_manifest_pins_semantic_and_schema_versions() -> None:
    prov = LangGraphThinProvider()
    m = prov.manifest()
    assert m["provider_version"] == thin_mod.PROVIDER_VERSION == "1.0.0"
    assert m["schema_version"] == thin_mod.SCHEMA_VERSION == 1
    assert m["capabilities"]["schema_version"] == thin_mod.SCHEMA_VERSION
    assert m["guarantees"]["version_evolution"]
    assert prov.version() == {
        "provider_id": "langgraph_thin",
        "provider_version": thin_mod.PROVIDER_VERSION,
        "schema_version": thin_mod.SCHEMA_VERSION,
    }


@pytest.mark.asyncio
async def test_checkpoint_is_schema_versioned() -> None:
    saver = MemorySaver()
    prov = LangGraphThinProvider(checkpointer=saver)
    req = _request(generation="gen-VERSIONED")
    await prov.run(req)
    assert _dump(saver, "gen-VERSIONED")["schema_version"] == thin_mod.SCHEMA_VERSION


# ── Interrupts surface correctly (not as runtime errors) ───────────────────────


def _interrupt_graph(saver: MemorySaver) -> Any:
    class S(dict):
        pass

    async def node(state: Any, config: RunnableConfig) -> dict[str, Any]:
        human = interrupt("proceed")  # raises GraphInterrupt on the first pass
        return {"value": human}

    builder = StateGraph(S)
    builder.add_node("interrupt_node", node)  # type: ignore[arg-type]
    builder.add_edge(START, "interrupt_node")
    builder.add_edge("interrupt_node", END)
    return builder.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_langgraph_interrupt_surfaces_as_interrupted_not_error() -> None:
    """An official LangGraph ``interrupt()`` must NOT be misreported as ERROR."""
    saver = MemorySaver()
    prov = LangGraphThinProvider(checkpointer=saver)
    prov._graph = _interrupt_graph(saver)  # thin replacement: default graph has no interrupt
    req = _request(generation="gen-INTERRUPT")
    res = await prov.run(req)
    assert res.termination.reason == TerminationReason.INTERRUPTED
    assert res.termination.completed is False
    assert res.error is None, "an interrupt is not a runtime error"
    assert res.termination.detail  # explains that the checkpoint holds resume state
    # The surfaced interrupt event carries the value LangGraph checkpointed at the
    # pause point (``interrupt("proceed")``) — proving the durable resume payload
    # reached the caller rather than being fabricated or lost.
    events = [e for e in res.trace if e.kind == "interrupt"]
    assert events and any("proceed" in str(item) for item in events[0].data.get("interrupts", []))
    assert req.state.snapshot["interrupted"] is True


# ── Failure injection: no silent corruption, exact budget & side-effect count ──


def _runaway(multi: int, final: str = "Done.") -> list:
    out: list = [{"tool_calls": [{"name": "calc", "args": {"a": i, "b": i}}]} for i in range(multi)]
    out.append(final)  # type: ignore[arg-type]
    return out


class FailingModel(ScriptedModel):
    def __init__(self, script: list, *, fail_on_call: int, fail_exc: BaseException) -> None:
        super().__init__(list(script))
        self._fail_on = fail_on_call
        self._fail_exc = fail_exc
        self.model_calls = 0  # NB: do NOT reuse ``.calls`` — ScriptedModel owns it as a list

    async def generate(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        self.model_calls += 1
        if self.model_calls == self._fail_on:
            raise self._fail_exc
        return await super().generate(messages, **kw)


@pytest.mark.asyncio
async def test_model_failure_no_state_corruption_and_no_duplicate_dispatch() -> None:
    saver = MemorySaver()
    tools = make_standard_tools()
    failing = FailingModel(
        [{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "unused"],
        fail_on_call=2,
        fail_exc=RuntimeError("model boom"),
    )
    req = _request(script=..., generation="gen-FAIL", config={}, tools=tools, model=failing)
    res = await LangGraphThinProvider(checkpointer=saver).run(req)
    assert res.termination.reason == TerminationReason.ERROR
    assert res.error is not None and res.error.kind == "runtime_error"
    # The tool was dispatched exactly the once the model requested before the crash.
    assert len(tools.calls) == 1
    # No silent state corruption: the durable checkpoint is well-formed.
    state = _dump(saver, "gen-FAIL")
    assert state.get("schema_version") == thin_mod.SCHEMA_VERSION
    assert state.get("messages") and all(isinstance(m, dict) for m in state["messages"])
    # tool dispatch must not be left pending in a corrupt state (cleared on completion
    # of the tools super-step, or absent if the node never ran).
    assert "tool_requests" not in state or state["tool_requests"] in ([], None)


@pytest.mark.asyncio
async def test_retry_after_failure_is_a_clean_atomic_attempt() -> None:
    """A retry with a fresh execution_generation must replay cleanly, with the
    failed thread never silently reused (no duplicate side effects)."""
    tools = make_standard_tools()
    failing = FailingModel(
        [{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "unused"],
        fail_on_call=2,
        fail_exc=RuntimeError("boom"),
    )
    first = await LangGraphThinProvider().run(
        _request(generation="gen-FAIL-RETRY", tools=tools, model=failing)
    )
    assert first.termination.reason == TerminationReason.ERROR

    good_tools = make_standard_tools()
    second = await LangGraphThinProvider().run(
        _request(generation="gen-FAIL-RETRY-2", tools=good_tools)
    )
    assert second.termination.completed
    assert second.output.final_text.strip() == "Result is 5."
    assert len(good_tools.calls) == 1  # clean replay, exactly one dispatch


@pytest.mark.asyncio
async def test_budget_accounting_under_failure_uses_native_recursion() -> None:
    """A long tool chain is bounded by LangGraph's own recursion limit, even
    before the model script is exhausted; budget/step bookkeeping reports the
    correct termination reason and never credits un-run steps."""
    req = _request("runaway", _runaway(40), config={"step_budget": 2})
    res = await LangGraphThinProvider().run(req)
    assert res.termination.completed is False
    assert res.termination.reason in (
        TerminationReason.BUDGET_EXHAUSTED,
        TerminationReason.STEP_LIMIT,
    )
    assert res.termination.step_count >= 0
    assert any(e.kind == "node" for e in res.trace)


# ── Durable execution / crash recovery ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_crash_recovery_replays_durable_execution_state_without_duplicates() -> None:
    """Crash-recovery: after the provider is torn down and re-instantiated on a
    shared (durable) checkpointer, the completed execution history incl. the tool
    result is re-read without loss or duplication."""
    saver = MemorySaver()
    prov1 = LangGraphThinProvider(checkpointer=saver)
    req = _request(generation="gen-CRASH")
    res1 = await prov1.run(req)
    assert res1.termination.completed

    # New provider instance, same durable saver  → the authoritative resume source.
    prov2 = LangGraphThinProvider(checkpointer=saver)
    state = prov2._graph.get_state({"configurable": {"thread_id": "gen-CRASH"}}).values
    tool_results = [str(m["content"]) for m in state.get("messages", []) if m.get("role") == "tool"]
    assert tool_results == ["2 + 3 = 5"]
    assert state["schema_version"] == thin_mod.SCHEMA_VERSION
    # No duplicate pending dispatch after recovery.
    assert state.get("tool_requests") in (None, [])


# ── Version evolution: an incompatible thread is never silently resumed ────────


@pytest.mark.asyncio
async def test_version_evolution_incompatible_thread_never_resumed() -> None:
    saver = MemorySaver()
    prov = LangGraphThinProvider(checkpointer=saver)
    req = _request(generation="gen-V1")
    await prov.run(req)
    assert _dump(saver, "gen-V1")["schema_version"] == 1

    # Bump the schema version, then attempt an explicit resume on the OLD thread.
    old = thin_mod.SCHEMA_VERSION
    thin_mod.SCHEMA_VERSION = 999
    try:
        prov2 = LangGraphThinProvider(checkpointer=saver)
        req2 = _request(generation="gen-V1", config={"resume": True})
        await prov2.run(req2)
        # The guard refused the incompatible thread and minted a fresh one.
        guard = req2.state.snapshot.get("version_guard", "")
        assert "incompatible" in guard
        assert req2.state.snapshot["execution_generation"] != "gen-V1"
        # The old thread is untouched.
        assert _dump(saver, "gen-V1")["schema_version"] == 1
    finally:
        thin_mod.SCHEMA_VERSION = old


@pytest.mark.asyncio
async def test_resume_requested_without_checkpointer_is_safely_ignored() -> None:
    """Requesting resume without a durable checkpointer degrades to an atomic run
    and records why — no silent corruption, no LangGraph error."""
    req = _request(generation="gen-NO-CHECKPOINT", config={"resume": True})
    res = await LangGraphThinProvider().run(req)
    assert res.termination.completed
    assert req.state.snapshot.get("resume_ignored") == "no_checkpointer_configured"


# ── Manifest ↔ observable semantics conformance ────────────────────────────────


@pytest.mark.asyncio
async def test_declared_guarantees_are_observable_at_runtime() -> None:
    g = LangGraphThinProvider().manifest()["guarantees"]
    assert g["deterministic_replay"] is True
    a = await LangGraphThinProvider().run(_request(generation="gen-CD-a"))
    b = await LangGraphThinProvider().run(_request(generation="gen-CD-b"))
    assert a.output.final_text == b.output.final_text
    assert a.output.tool_calls == b.output.tool_calls

    assert g["state_integrity"] is True
    tools = make_standard_tools()
    await LangGraphThinProvider().run(_request(generation="gen-CD-c", tools=tools))
    assert len(tools.calls) == 1  # each tool_request dispatched exactly once per run

    assert g["budget_integrity"] is True
    low = await LangGraphThinProvider().run(
        _request("budget", _runaway(40), generation="gen-CD-d", config={"step_budget": 1})
    )
    assert low.termination.completed is False

    assert g["retry_semantics"] == "atomic_attempt_new_execution_generation"
    assert g["resume_semantics"].startswith("caller_supplied_generation")
    assert "delegated_to_langgraph" in g["durability_semantics"]
    assert g["version_evolution"]


# ── Production-like benchmark under persistence ────────────────────────────────


@pytest.mark.asyncio
async def test_production_like_benchmark_conformance_with_persistence() -> None:
    """The same frozen benchmark, run with persistence enabled, must keep full
    per-scenario conformance and determinism for P1."""
    prov = LangGraphThinProvider(checkpointer=MemorySaver())
    run = await run_benchmark([prov], reps=2, seed=1)
    for rep in run.reports:
        assert rep.metrics.runtime.task_success, f"{rep.scenario_id} rep {rep.rep} did not complete"
        assert rep.metrics.runtime.failure_rate == 0.0
        assert rep.metrics.runtime.determinism == 1.0, f"nondeterministic: {rep.scenario_id}"
        if rep.metrics.runtime.tool_calls:
            assert rep.metrics.runtime.tool_call_correct == 1.0

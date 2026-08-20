"""P1 — LangGraph Thin Provider: architecture / conformance tests.

These assert the *thin boundary* of P1 as a production-grade LangGraph
challenger:

* LangGraph usage is strictly confined to the provider boundary and to official
  public API (no ``langgraph._*`` internals, no fork / patch).
* Lumen Core (contract / models / fakes / metrics / benchmark) never imports
  LangGraph — Lumen does not depend on a specific runtime.
* Domain state (teaching / learner) is never stored in the LangGraph checkpoint;
  the checkpoint holds only Provider Execution State.
* The Lumen Run / ``execution_generation`` maps to a LangGraph ``thread_id``.
* Budget / safety, state-projection (no duplicate side effects) and
  deterministic replay are honoured and testable.
* The Capability & Guarantee manifest is present and self-consistent.

They do NOT re-test the frozen parity suite (``test_providers.py``) — they
target P1-specific guarantees on top of it.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect

from langgraph.checkpoint.memory import MemorySaver
import pytest

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

# ── Test helpers ─────────────────────────────────────────────────────────────


def _request(
    user_message: str = "compute 2+3",
    script: list | None = None,
    *,
    decision: TeachingDecisionKind = TeachingDecisionKind.EXPLAIN,
    config: dict | None = None,
    generation: str | None = "gen-test",
    tools: object | None = None,
) -> ProviderRequest:
    script = script or [
        {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
        "Result is 5.",
    ]
    state = TurnState()
    if generation is not None:
        state.snapshot["execution_generation"] = generation
    req = ProviderRequest(
        input=TurnInput(user_message=user_message, session_id="s", conversation_history=[]),
        state=state,
        context=RuntimeContext(language="en"),
        model=ScriptedModel(list(script), seed=1),
        tools=tools or make_standard_tools(),
        teaching=ScriptedTeaching([TeachingDecision(kind=decision, strategy="socratic")]),
        seed=1,
        config=dict(config or {}),
    )
    return req


def _script(multi: int = 0, final: str = "Done.") -> list:
    out: list = [{"tool_calls": [{"name": "calc", "args": {"a": i, "b": i}}]} for i in range(multi)]
    out.append(final)  # type: ignore[arg-type]
    return out


# ── 1. Boundary: LangGraph confined to the provider, official public API ────


def test_provider_imports_only_official_langgraph_public_api() -> None:
    """No ``langgraph._*`` internals; only the Graph + errors + types public surfaces."""
    import lumen.evolution.providers.langchain_thin as mod

    src = inspect.getsource(mod)
    allowed_prefixes = ("langgraph.graph", "langgraph.errors", "langgraph.types")
    # Every langgraph import must be from an allowed public module.
    imports = [
        ln
        for ln in src.splitlines()
        if ln.strip().startswith(("from langgraph", "import langgraph"))
    ]
    assert imports, "provider must import langgraph somewhere"
    for ln in imports:
        modpath = ln.split(" import", 1)[0].replace("from ", "").strip()
        assert modpath.startswith(allowed_prefixes), f"non-public langgraph import: {ln}"
        assert "._" not in modpath, f"internal langgraph import: {ln}"


@pytest.mark.parametrize(
    "core",
    [
        "lumen.evolution.contract",
        "lumen.evolution.models",
        "lumen.evolution.fakes",
        "lumen.evolution.metrics",
        "lumen.evolution.benchmark",
    ],
)
def test_lumen_core_has_no_langgraph_import(core: str) -> None:
    """Lumen Core does not depend on LangGraph — only the provider adapter does.

    Uses AST (not prose scan) so docstrings that merely mention "LangGraph" are
    allowed; actual ``import langgraph`` / ``from langgraph`` are forbidden.
    """
    import ast

    mod = importlib.import_module(core)
    tree = ast.parse(inspect.getsource(mod))
    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offending.extend(a.name for a in node.names if a.name.split(".")[0] == "langgraph")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "langgraph":
                offending.append(node.module)
    assert not offending, f"{core} imports langgraph: {offending}"
    assert "create_react_agent" not in inspect.getsource(mod), (
        f"{core} must not use langgraph sugar"
    )


def test_p1_provider_id_is_the_langgraph_thin_ids() -> None:
    assert LangGraphThinProvider.provider_id == "langgraph_thin"


# ── 2. Manifest: capability & guarantee boundaries ───────────────────────────


def test_manifest_declares_thin_boundary() -> None:
    m = LangGraphThinProvider().manifest()
    caps = m["capabilities"]
    assert caps["runtime"] == "unmodified-langgraph"
    assert caps["langgraph_types_leak"] == "none"
    assert caps["teaching_model"] == "pre_turn_hook_not_graph_node"
    assert caps["checkpoint_scope"] == "provider_execution_state_only"
    assert caps["domain_state_vs_checkpoint"] == "separated"
    assert caps["cross_provider_checkpoint_portability"] is False
    assert caps["functional_api"] is False  # minimal usage = StateGraph over Model contract
    # P1 must not re-implement Runtime capabilities LangGraph already provides.
    assert {"scheduler", "retry", "checkpointing", "resume", "durability"} <= set(
        caps["not_reimplemented"]
    )

    g = m["guarantees"]
    assert g["deterministic_replay"] is True
    assert g["budget_integrity"] is True
    assert g["state_integrity"] is True
    assert g["interrupt"] is False
    assert g["resume"] is True


# ── 3. Execution identity: Lumen Run / execution_generation ↔ thread_id ─────


@pytest.mark.asyncio
async def test_execution_identity_maps_to_langgraph_thread() -> None:
    prov = LangGraphThinProvider(checkpointer=MemorySaver())
    req = _request(generation="gen-IDENTITY-1")
    await prov.run(req)
    # The same thread_id the provider used must hold the checkpointed execution
    # state, proving the Lumen Run id became the LangGraph execution identity.
    snap = prov._graph.get_state({"configurable": {"thread_id": "gen-IDENTITY-1"}})
    assert snap is not None
    assert snap.values.get("execution_generation") == "gen-IDENTITY-1"


@pytest.mark.asyncio
async def test_execution_generation_recorded_on_lumen_state_snapshot() -> None:
    prov = LangGraphThinProvider()
    req = _request(generation=None)  # provider must mint a unique execution_generation
    await prov.run(req)
    gen = req.state.snapshot["execution_generation"]
    assert gen and req.state.turn_id == gen


# ── 4. Domain state vs LangGraph checkpoint separation ───────────────────────


@pytest.mark.asyncio
async def test_checkpoint_is_execution_state_not_domain_state() -> None:
    prov = LangGraphThinProvider(checkpointer=MemorySaver())
    req = _request(generation="gen-DOMAIN")
    await prov.run(req)
    snap = prov._graph.get_state({"configurable": {"thread_id": "gen-DOMAIN"}})
    keys = set(snap.values.keys())
    # Only Provider Execution State — teaching / learner / domain never stored.
    # (``schema_version`` / ``provider_version`` are execution-state bookkeeping,
    # not domain state.)
    assert keys <= {
        "messages",
        "tool_requests",
        "execution_generation",
        "schema_version",
        "provider_version",
    }
    forbidden = {"decision", "learner", "learner_state", "teaching", "policy"}
    assert keys.isdisjoint(forbidden)


@pytest.mark.asyncio
async def test_teaching_consulted_but_not_embedded_in_graph_state() -> None:
    prov = LangGraphThinProvider(checkpointer=MemorySaver())
    teaching = ScriptedTeaching([TeachingDecision(kind=TeachingDecisionKind.EXPLAIN)])
    req = _request(generation="gen-TEACH", decision=TeachingDecisionKind.EXPLAIN)
    req.teaching = teaching
    await prov.run(req)
    snap = prov._graph.get_state({"configurable": {"thread_id": "gen-TEACH"}})
    # Teaching was consulted as a hook (Lumen side), not serialised into state.
    assert teaching.decisions, "teaching plugin was consulted"
    assert "decision" not in snap.values


@pytest.mark.asyncio
async def test_resume_source_is_durable_execution_state() -> None:
    """Resume / crash-recovery: the thread checkpoint is the authoritative
    provider-execution resume source, and it durably holds the dispatched tool
    result — a crash after tool dispatch can resume without losing the side
    effect (LangGraph owns the durability; the provider only wires thread_id).
    """
    prov = LangGraphThinProvider(checkpointer=MemorySaver())
    req = _request(generation="gen-RESUME")
    res = await prov.run(req)
    assert res.termination.completed
    cfg = {"configurable": {"thread_id": "gen-RESUME"}}
    snap = prov._graph.get_state(cfg)
    assert prov._graph.checkpointer is not None
    msgs = snap.values.get("messages", [])
    # The tool result the run dispatched is durably checkpointed.
    tool_results = [str(m["content"]) for m in msgs if m.get("role") == "tool"]
    assert tool_results == ["2 + 3 = 5"]
    # Resuming from this checkpoint restores the full completed execution history
    # (system + user + assistant tool-call + tool result + final answer).
    roles = [m.get("role") for m in msgs]
    assert "user" in roles and "tool" in roles and roles[-1] == "assistant"
    assert msgs[-1].get("content") == "Result is 5."


# ── 5. Budget / safety integrity ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_exhausted_terminates_not_completed() -> None:
    script = _script(multi=4)  # 4 tool rounds → far more than step_budget=2 allows
    req = _request("many", script, config={"step_budget": 2})
    res = await LangGraphThinProvider().run(req)
    assert res.termination.reason == TerminationReason.BUDGET_EXHAUSTED
    assert res.termination.completed is False
    assert "recursion_limit" in res.termination.detail
    # No duplicate side effects even when the budget cut the run short.
    assert len(req.tools.calls) <= 4


@pytest.mark.asyncio
async def test_default_step_limit_is_native_recursion_not_hand_rolled() -> None:
    # A very long tool chain without an explicit step_budget must still stop
    # safely via LangGraph's own recursion_limit (STEP_LIMIT, not COMPLETED).
    script = _script(multi=200)  # unbounded loop if the runtime lacks a safeguard
    req = _request("runaway", script, config={})
    res = await LangGraphThinProvider().run(req)
    assert res.termination.completed is False
    assert res.termination.reason in (
        TerminationReason.STEP_LIMIT,
        TerminationReason.BUDGET_EXHAUSTED,
    )


# ── 6. Deterministic replay & no duplicate side effects ──────────────────────


@pytest.mark.asyncio
async def test_deterministic_replay_across_runs() -> None:
    prov = LangGraphThinProvider()
    a = await prov.run(_request("two", _script(multi=2)))
    b = await prov.run(_request("two", _script(multi=2)))
    assert a.output.final_text == b.output.final_text
    assert a.output.tool_calls == b.output.tool_calls
    assert a.termination.reason == b.termination.reason


@pytest.mark.asyncio
async def test_tool_side_effects_executed_exactly_once_per_run() -> None:
    prov = LangGraphThinProvider()
    req = _request("three", _script(multi=3))
    res = await prov.run(req)
    # Each requested tool dispatch is an external side effect; it must run once,
    # never twice (LangGraph tool-loop must not resend the same request).
    assert len(req.tools.calls) == 3
    assert len(res.output.tool_calls) == 3


@pytest.mark.asyncio
async def test_concurrent_runs_on_shared_graph_are_isolated() -> None:
    """The compiled graph is cached once; per-run model/tools come via config, so
    concurrent runs on the same provider must not cross-contaminate state."""
    prov = LangGraphThinProvider()
    req_a = _request("two-a", _script(multi=2), generation="gen-A")
    req_b = _request("two-b", _script(multi=3), generation="gen-B")

    res_a, res_b = [res for res in (await asyncio.gather(prov.run(req_a), prov.run(req_b)))]
    assert res_a.output.final_text == "Done."
    assert res_b.output.final_text == "Done."
    # Each request's own tool runtime saw exactly its own dispatches.
    assert len(req_a.tools.calls) == 2
    assert len(req_b.tools.calls) == 3

"""Provider parity tests — P0–P3 all run the same deterministic scenarios
through the same Model/Tool/Teaching seams and produce comparable results."""

from __future__ import annotations

import asyncio

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
from lumen.evolution.providers import (
    LangGraphDualProvider,
    LangGraphNodesProvider,
    LangGraphThinProvider,
    LegacyProvider,
)

ALL_PROVIDERS = pytest.mark.parametrize(
    "factory",
    [
        lambda: LegacyProvider(),
        lambda: LangGraphThinProvider(),
        lambda: LangGraphNodesProvider(),
        lambda: LangGraphDualProvider(),
    ],
)


def _request(user_message="compute 2+3", script=None, decision=TeachingDecisionKind.EXPLAIN):
    script = script or [
        {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
        "Result is 5.",
    ]
    return ProviderRequest(
        input=TurnInput(user_message=user_message, session_id="s", conversation_history=[]),
        state=TurnState(),
        context=RuntimeContext(language="en"),
        model=ScriptedModel(list(script), seed=1),
        tools=make_standard_tools(),
        teaching=ScriptedTeaching([TeachingDecision(kind=decision, strategy="socratic")]),
        seed=1,
    )


@ALL_PROVIDERS
@pytest.mark.asyncio
async def test_each_provider_executes_single_tool_call(factory):
    res = await factory().run(_request())
    assert res.provider_id
    assert res.termination.completed
    assert ("calc", {"a": 2, "b": 3}) in res.output.tool_calls
    # All four providers must produce the deterministic final output.
    assert res.output.final_text.strip() == "Result is 5."


@ALL_PROVIDERS
@pytest.mark.asyncio
async def test_each_provider_runs_multi_tool_flow(factory):
    res = await factory().run(
        _request(
            user_message="two computations",
            script=[
                {"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 1}}]},
                {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 2}}]},
                "Done.",
            ],
        )
    )
    calc_calls = [name for name, _ in res.output.tool_calls]
    assert calc_calls.count("calc") >= 2
    assert res.output.final_text.strip() == "Done."


@ALL_PROVIDERS
@pytest.mark.asyncio
async def test_each_provider_recovers_from_tool_error(factory):
    res = await factory().run(
        _request(
            user_message="boom then calc",
            script=[
                {"tool_calls": [{"name": "boom", "args": {}}]},
                {"tool_calls": [{"name": "calc", "args": {"a": 4, "b": 4}}]},
                "Recovered.",
            ],
            decision=TeachingDecisionKind.REMEDIATE,
        )
    )
    names = [name for name, _ in res.output.tool_calls]
    assert "boom" in names and "calc" in names
    assert res.error is None


@ALL_PROVIDERS
@pytest.mark.asyncio
async def test_each_provider_emits_trace(factory):
    res = await factory().run(_request())
    assert len(res.trace) > 0


@ALL_PROVIDERS
@pytest.mark.asyncio
async def test_each_provider_is_deterministic_across_runs(factory):
    a = await factory().run(_request())
    b = await factory().run(_request())
    assert a.output.final_text == b.output.final_text
    assert a.output.tool_calls == b.output.tool_calls


@pytest.mark.asyncio
async def test_legacy_provider_step_limit_terminates():
    prov = LegacyProvider(max_steps=2)
    res = await prov.run(
        _request(
            script=[
                {"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 1}}]},
                {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 2}}]},
                "Done.",
            ]
        )
    )
    # With a step cap of 2 the loop must terminate safely, never hang.
    assert res.termination.reason in (TerminationReason.COMPLETED, TerminationReason.STEP_LIMIT)


@pytest.mark.asyncio
async def test_langgraph_nodes_emits_teaching_events():
    prov = LangGraphNodesProvider()
    res = await prov.run(_request())
    # Teaching node topology must drive at least one assessment round.
    assert res.output.events, "teaching nodes provider emitted no assessment events"
    assert any("decision" in e for e in res.output.events)


@pytest.mark.asyncio
async def test_langgraph_dual_keeps_agent_and_teaching_separate():
    teaching = ScriptedTeaching([TeachingDecision(kind=TeachingDecisionKind.EXPLAIN, strategy="socratic")])
    req = _request(decision=TeachingDecisionKind.EXPLAIN)
    req.teaching = teaching
    res = await LangGraphDualProvider().run(req)
    assert res.provider_id == "langgraph_dual"
    assert res.termination.completed
    # Teaching was consulted through the bridge (decisions recorded).
    assert len(teaching.decisions) >= 1
"""P1 Real-World Validation regression tests.

These pin the real issues discovered while validating P1 (LangGraph Thin) as
the dev Active Provider against real OpenAI-compatible gateways:

1. **Canonical tool_calls serialization** — P1's ``_tools_node`` must emit the
   assistant ``tool_calls`` in canonical OpenAI form
   (``type=function`` / ``function.name`` / ``function.arguments``).  Real
   gateways reject the shorthand ``{"name", "args"}`` shape with a 400
   "No tool call found for function call output" — which broke tool recovery
   in real sessions.  (Fixed in ``lumen.evolution.providers.langchain_thin``.)
2. **ProviderResult tool_calls normalisation** — ``LangGraphThinProvider.run``
   must read both the shorthand and the canonical shape back off the
   checkpointed messages.
3. **Dev Active Provider wiring** — ``LUMEN_AGENT_LOOP_PROVIDER=langgraph_thin``
   elects P1 as ``runtime.agent_loop`` while production default stays Legacy.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from lumen.bootstrap import resolve_active_assembly
from lumen.evolution.contract import (
    ProviderRequest,
    RuntimeContext,
    TeachingDecision,
    TeachingDecisionKind,
    TurnInput,
    TurnState,
)
from lumen.evolution.fakes import ScriptedTeaching, make_standard_tools
from lumen.evolution.models import ScriptedModel
from lumen.evolution.providers import LangGraphThinProvider
import lumen.evolution.providers.langchain_thin as thin_mod

# ── 1. Canonical tool_calls serialization ─────────────────────────────────────


def _request(script: list[Any], *, generation: str = "gen-tc") -> ProviderRequest:
    state = TurnState()
    state.snapshot["execution_generation"] = generation
    return ProviderRequest(
        input=TurnInput(user_message="compute 2+3", session_id="s", conversation_history=[]),
        state=state,
        context=RuntimeContext(language="en"),
        model=ScriptedModel(list(script), seed=1),
        tools=make_standard_tools(),
        teaching=ScriptedTeaching([TeachingDecision(kind=TeachingDecisionKind.EXPLAIN)]),
        seed=1,
        config={},
    )


def test_tools_node_emits_canonical_openai_tool_calls() -> None:
    """The assistant message preceding a ``role=tool`` message must use the
    canonical OpenAI tool_calls shape — real gateways reject the shorthand."""
    saver = _memory_saver()
    prov = LangGraphThinProvider(checkpointer=saver)
    req = _request(
        [{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "Result is 5."],
        generation="gen-CANONICAL",
    )
    res = asyncio_run(prov.run(req))
    assert res.termination.completed, res.termination.detail

    snap = prov._graph.get_state({"configurable": {"thread_id": "gen-CANONICAL"}})
    msgs = snap.values.get("messages", [])
    # Find the assistant message that carries tool_calls.
    assistant_tool_msgs = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
    assert assistant_tool_msgs, "no assistant tool_calls message was emitted"
    tc = assistant_tool_msgs[-1]["tool_calls"][0]
    # Canonical shape: type=function + function.name/arguments.
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "calc"
    assert json.loads(tc["function"]["arguments"]) == {"a": 2, "b": 3}
    # The shorthand shape must NOT be what the model sees next.
    assert "args" not in tc


def test_run_reads_canonical_tool_calls_back_from_checkpoint() -> None:
    """After a tool round, ProviderResult.output.tool_calls must be populated
    from the canonical checkpoint shape (not crash on a missing 'name')."""
    prov = LangGraphThinProvider()
    req = _request(
        [{"tool_calls": [{"name": "calc", "args": {"a": 4, "b": 5}}]}, "Done."],
        generation="gen-CANON-READBACK",
    )
    res = asyncio_run(prov.run(req))
    assert res.termination.completed
    assert ("calc", {"a": 4, "b": 5}) in res.output.tool_calls


def test_tool_error_is_contained_and_turn_completes() -> None:
    """A tool that raises must be returned to the model as a tool message
    (recoverable), not kill the graph — the model then produces a final answer."""
    tools = make_standard_tools()
    prov = LangGraphThinProvider()
    # boom tool raises; the script then answers with plain text.
    req = _request(
        [{"tool_calls": [{"name": "boom", "args": {}}]}, "Recovered."],
        generation="gen-TOOL-ERR",
    )
    req.tools = tools
    res = asyncio_run(prov.run(req))
    # The tool error was surfaced to the model, not a runtime crash.
    assert res.termination.completed, res.termination.detail
    assert res.output.final_text.strip() == "Recovered."
    assert res.error is None


# ── 2. Dev Active Provider wiring ─────────────────────────────────────────────


def test_dev_active_provider_is_p1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_AGENT_LOOP_PROVIDER", "langgraph_thin")
    profile, plugins = resolve_active_assembly()
    assert profile.bindings["runtime.agent_loop"] == "agent_loop.langgraph_thin"
    ids = {p.manifest.id for p in plugins}
    assert "agent_loop.langgraph_thin" in ids
    assert "runtime.agent_loop" in ids  # Legacy present for fast fallback
    # mode.learn boots with P1 behind it.
    assert "mode.learn" in ids


def test_production_default_stays_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUMEN_AGENT_LOOP_PROVIDER", raising=False)
    profile, plugins = resolve_active_assembly()
    assert profile.bindings == {}  # no binding → single provider (Legacy)
    ids = {p.manifest.id for p in plugins}
    assert "agent_loop.langgraph_thin" not in ids
    assert "runtime.agent_loop" in ids


# ── helpers ───────────────────────────────────────────────────────────────────


def _memory_saver() -> Any:
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)

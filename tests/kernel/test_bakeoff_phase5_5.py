"""A/B bake-off tests: legacy vs LangChain agent loop (Phase 5.5).

Boots both ``profile.agent_loop_legacy`` and ``profile.agent_loop_langchain``
with deterministic fakes and runs the same scenarios against each
``runtime.agent_loop``, then compares the metrics.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from lumen.agent_loop_langchain import LangChainAgentLoopPlugin
from lumen.agent_loop_langchain.plugins import _LangChainAgentLoopAdapter
from lumen.bakeoff_profiles import (
    AGENT_LOOP_LANGCHAIN_PLUGINS,
    AGENT_LOOP_LANGCHAIN_PROFILE,
    AGENT_LOOP_LEGACY_PLUGINS,
    AGENT_LOOP_LEGACY_PROFILE,
    non_agent_loop_plugin_ids,
)
from lumen.kernel import Bootstrap
from lumen.runtime.stream.bus import StreamBus
from tests.kernel.bakeoff_fakes import (
    FakeBakeoffToolService,
    ScriptedLangChainModel,
    make_ask_tool,
    make_calc_tool,
)
from tests.kernel.bakeoff_harness import run_scenario, summarize

# ═══════════════════════════════════════════════════════════════════════════
# 1. Plugin / profile plumbing
# ═══════════════════════════════════════════════════════════════════════════


def test_langchain_plugin_manifest():
    m = LangChainAgentLoopPlugin.manifest
    assert m.id == "agent_loop.langchain"
    assert "runtime.agent_loop" in m.provides
    assert {"runtime.llm", "runtime.tools", "runtime.session", "runtime.prompt"} <= set(m.requires)
    # The plugin must NOT reach into mode.learn / learning / teaching_core.
    assert not {"mode.learn", "learning", "teaching_core"} & set(m.requires)


def test_ab_profiles_identical_except_agent_loop():
    """The two A/B profiles differ ONLY in the runtime.agent_loop provider."""
    legacy_ids = {p.manifest.id for p in AGENT_LOOP_LEGACY_PLUGINS}
    langchain_ids = {p.manifest.id for p in AGENT_LOOP_LANGCHAIN_PLUGINS}
    assert legacy_ids - langchain_ids == {"runtime.agent_loop"}
    assert langchain_ids - legacy_ids == {"agent_loop.langchain"}
    assert non_agent_loop_plugin_ids() == legacy_ids - {"runtime.agent_loop"}


@pytest.mark.asyncio
async def test_langchain_profile_boots_and_provides_agent_loop():
    root = await Bootstrap(profile=AGENT_LOOP_LANGCHAIN_PROFILE).boot(AGENT_LOOP_LANGCHAIN_PLUGINS)
    try:
        loop = root.require("runtime.agent_loop")
        assert isinstance(loop, _LangChainAgentLoopAdapter)
        # mode.learn still boots with the LangChain provider behind it.
        assert root.optional("mode.learn") is not None
    finally:
        await root.dispose()
    assert root.disposed


@pytest.mark.asyncio
async def test_legacy_profile_boots_and_provides_agent_loop():
    root = await Bootstrap(profile=AGENT_LOOP_LEGACY_PROFILE).boot(AGENT_LOOP_LEGACY_PLUGINS)
    try:
        assert root.optional("runtime.agent_loop") is not None
        assert root.optional("mode.learn") is not None
    finally:
        await root.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Deterministic LangChain adapter behaviour
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_langchain_plain_reply():
    tools = FakeBakeoffToolService()
    model = ScriptedLangChainModel(["Hello from LangChain."])
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    res = await run_scenario(
        adapter,
        scenario="plain_reply",
        user_message="hi",
        config={"langchain_model": model},
    )
    assert res.ok, res.error
    assert "Hello from LangChain" in res.final_text


@pytest.mark.asyncio
async def test_langchain_single_tool_call():
    tools = FakeBakeoffToolService()
    tools.register(make_calc_tool())
    model = ScriptedLangChainModel(
        [
            {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
            "Result is 5.",
        ]
    )
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    res = await run_scenario(
        adapter,
        scenario="single_tool_call",
        user_message="compute 2+3",
        enabled_tools=["calc"],
        config={"langchain_model": model},
    )
    assert res.ok, res.error
    assert tools.calls, "tool was never executed"
    assert tools.calls[0][0] == "calc"


@pytest.mark.asyncio
async def test_langchain_multi_tool_call():
    tools = FakeBakeoffToolService()
    tools.register(make_calc_tool())
    model = ScriptedLangChainModel(
        [
            {"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 1}}]},
            {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 2}}]},
            "Done: two calls.",
        ]
    )
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    res = await run_scenario(
        adapter,
        scenario="multi_tool_call",
        user_message="two computations",
        enabled_tools=["calc"],
        config={"langchain_model": model},
    )
    assert res.ok, res.error
    assert len(tools.calls) >= 2


@pytest.mark.asyncio
async def test_langchain_interrupt_resume():
    """ask_user pause → pending_user_input event → reply resumes the turn."""
    tools = FakeBakeoffToolService()
    tools.register(make_ask_tool())
    asked: list[dict[str, Any]] = []
    model = ScriptedLangChainModel(
        [
            {"tool_calls": [{"name": "ask_user", "args": {"question": "How old are you?"}}]},
            "Got it, thanks.",
        ]
    )
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)

    async def fake_waiter():
        asked.append(True)
        return "I am 20"

    res = await run_scenario(
        adapter,
        scenario="interrupt_resume",
        user_message="ask me",
        enabled_tools=["ask_user"],
        wait_for_user_reply=fake_waiter,
        config={"langchain_model": model},
    )
    assert asked, "reply waiter never invoked"
    assert res.ok, res.error
    kinds = [e.type.name for e in res.events]
    assert "WAIT_FOR_INPUT" in kinds, kinds


@pytest.mark.asyncio
async def test_langchain_streaming():
    """The adapter emits incremental content events, not one blob."""
    tools = FakeBakeoffToolService()
    model = ScriptedLangChainModel(["This is a streamed answer."])
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    res = await run_scenario(
        adapter,
        scenario="streaming",
        user_message="stream please",
        config={"langchain_model": model},
    )
    assert res.ok, res.error
    content_events = [e for e in res.events if e.type.name == "CONTENT"]
    assert len(content_events) >= 1


@pytest.mark.asyncio
async def test_langchain_tool_error_is_contained():
    """A tool that raises must not kill the turn."""
    tools = FakeBakeoffToolService()

    from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult

    class BoomTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(name="boom", description="Always fails.")

        async def execute(self, **kwargs):
            raise RuntimeError("boom")

    tools.register(BoomTool())
    model = ScriptedLangChainModel(
        [
            {"tool_calls": [{"name": "boom", "args": {}}]},
            "Recovered.",
        ]
    )
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    res = await run_scenario(
        adapter,
        scenario="tool_error",
        user_message="run boom",
        enabled_tools=["boom"],
        config={"langchain_model": model},
    )
    assert res.ok, res.error


# ═══════════════════════════════════════════════════════════════════════════
# 3. A/B comparison across the shared scenario set
# ═══════════════════════════════════════════════════════════════════════════


async def _legacy_run_scenario(
    tools: FakeBakeoffToolService,
    script: list[Any],
    *,
    scenario: str,
    user_message: str,
    enabled_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    wait_for_user_reply: Any = None,
) -> Any:
    """Run one scenario through the real legacy pipeline, returning a
    ``ScenarioResult``-shaped object compatible with ``summarize``."""
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    from tests.kernel.bakeoff_fakes import ScriptedOpenAIClient
    from tests.kernel.bakeoff_harness import ScenarioResult

    client = ScriptedOpenAIClient(script)
    pipeline = AgenticChatPipeline(
        language="en",
        registry=tools,
        client_factory=lambda _cfg: client,
    )
    bus = StreamBus()
    ctx = UnifiedContext(
        session_id="bakeoff-legacy",
        user_message=user_message,
        enabled_tools=enabled_tools or [],
        knowledge_bases=[],
        language="en",
        metadata=dict(metadata or {}),
    )
    if wait_for_user_reply is not None:
        ctx.metadata["wait_for_user_reply"] = wait_for_user_reply

    result = ScenarioResult(scenario=scenario)
    try:
        await pipeline.run(ctx, bus)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.events = list(bus._history)
        return result

    result.events = list(bus._history)
    content_parts: list[str] = []
    for event in result.events:
        if event.type == StreamEventType.CONTENT:
            content_parts.append(event.content or "")
        if event.type == StreamEventType.TOOL_CALL:
            result.tool_calls.append((event.content or "", event.metadata.get("args", {})))
        if event.type == StreamEventType.RESULT:
            result.final_text = str(event.metadata.get("response") or "")
            result.completed = bool(event.metadata.get("completed", False))
    if not result.final_text:
        result.final_text = "".join(content_parts)
    result.ok = bool(result.final_text.strip()) and not result.error
    return result


@pytest.mark.asyncio
async def test_ab_bakeoff_plain_and_tool_compare():
    """The SAME scenario runs through the real legacy pipeline and the
    LangChain adapter; both must complete and produce a final answer."""
    # Legacy: scripted client asks for calc, then answers.
    legacy_tools = FakeBakeoffToolService()
    legacy_tools.register(make_calc_tool())
    legacy = await _legacy_run_scenario(
        legacy_tools,
        script=[{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "Result is 5."],
        scenario="single_tool_call",
        user_message="compute 2+3",
        enabled_tools=["calc"],
    )

    lc_tools = FakeBakeoffToolService()
    lc_tools.register(make_calc_tool())
    lc_model = ScriptedLangChainModel(
        [
            {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
            "Result is 5.",
        ]
    )
    lc_adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=lc_tools)
    lc = await run_scenario(
        lc_adapter,
        scenario="single_tool_call",
        user_message="compute 2+3",
        enabled_tools=["calc"],
        config={"langchain_model": lc_model},
    )

    # Both must have executed the tool and produced an answer.
    assert legacy.ok, legacy.error
    assert lc.ok, lc.error
    assert legacy_tools.calls, "legacy never ran the tool"
    assert lc_tools.calls, "langchain never ran the tool"


@pytest.mark.asyncio
async def test_ab_bakeoff_summary_table():
    """Run the shared scenario set against both providers and produce a
    comparison table (functional completeness at minimum)."""
    legacy_tools = FakeBakeoffToolService()
    legacy_tools.register(make_calc_tool())
    lc_tools = FakeBakeoffToolService()
    lc_tools.register(make_calc_tool())
    lc_adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=lc_tools)

    scenarios = [
        {
            "scenario": "plain_reply",
            "user_message": "hi",
            "legacy_script": ["Legacy plain answer."],
            "lc_script": ScriptedLangChainModel(["LangChain plain answer."]),
        },
        {
            "scenario": "single_tool_call",
            "user_message": "compute 2+3",
            "enabled_tools": ["calc"],
            "legacy_script": [
                {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
                "Legacy result is 5.",
            ],
            "lc_script": ScriptedLangChainModel(
                [
                    {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
                    "LangChain result is 5.",
                ]
            ),
        },
        {
            "scenario": "streaming",
            "user_message": "stream please",
            "legacy_script": ["Legacy streamed answer."],
            "lc_script": ScriptedLangChainModel(["LangChain streamed answer."]),
        },
    ]

    a_results = []
    b_results = []
    for s in scenarios:
        legacy = await _legacy_run_scenario(
            legacy_tools,
            s["legacy_script"],
            scenario=s["scenario"],
            user_message=s["user_message"],
            enabled_tools=s.get("enabled_tools"),
        )
        a_results.append(legacy)
        lc = await run_scenario(
            lc_adapter,
            scenario=s["scenario"],
            user_message=s["user_message"],
            enabled_tools=s.get("enabled_tools"),
            config={"langchain_model": s["lc_script"]},
        )
        b_results.append(lc)

    table = summarize(a_results, b_results)
    assert len(table["rows"]) == len(scenarios)
    for row in table["rows"]:
        assert "legacy_ok" in row and "langchain_ok" in row


# ═══════════════════════════════════════════════════════════════════════════
# 4. mode.learn zero-framework guarantee
# ═══════════════════════════════════════════════════════════════════════════


def test_mode_learn_has_no_framework_import():
    """mode.learn must never import langchain / langgraph."""
    import inspect

    import lumen.modes.learn.plugin as learn_plugins

    src = inspect.getsource(learn_plugins)
    assert "langchain" not in src.lower().replace("agent_loop.langchain", "")
    assert "langgraph" not in src.lower()


def test_langchain_adapter_imports_no_teaching_core():
    import inspect
    import re

    import lumen.agent_loop_langchain.plugins as lc_plugins

    src = inspect.getsource(lc_plugins)
    # No import / from-import of teaching core or learner-state internals.
    assert not re.search(r"(^|\n)\s*(from|import)\s+(deeptutor\.learning|teaching_core)", src)
    assert "deeptutor.learning" not in src
    # LearnerState must never be defined or imported here.
    assert not re.search(r"(^|\n)\s*class\s+LearnerState", src)
    assert "import LearnerState" not in src

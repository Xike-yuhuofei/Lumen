"""Bake-off v1 — frozen Agent Loop Provider benchmark (legacy vs LangChain).

This is the FROZEN A/B benchmark used to decide the production
``runtime.agent_loop`` provider.  It answers one question only:

    With identical LLM (deterministic fake), tools, scripts, materials,
    context and environment, which provider most reliably, simply and
    cheaply *executes* the already-decided teaching actions of Learn Mode?

It deliberately does NOT compare model quality, re-design the loop, or
modify teaching core.  Both providers are driven through the SAME
deterministic scripts and tools (``tests/kernel/bakeoff_fakes.py``) so
control variables are held constant.  ``ScriptedOpenAIClient`` (legacy)
and ``ScriptedLangChainModel`` (LangChain) both consume the scripts in
linear order, so every multi-round flow replays identically on both sides.

Frozen scenarios map onto the 9 required categories:

 1 single_tool_call         — single tool call
 2 multi_tool_sequential    — sequential multi-tool execution
 3 tool_error_recovery      — tool error / retry / recovery
 4 structured_args          — structured arguments / output
 5 streaming                — incremental content streaming
 6 ask_user_interrupt_resume— pause / interrupt / resume (ask_user)
 7 cancellation             — mid-turn cancellation, no hang
 8 long_session_continuity  — long context / long session (history carried)
 9 learn_turn               — Learn Mode full E2E (mastery mount/bind/prompt)

Metrics: success rate (per rep + replay-stable), tool-selection and
argument correctness, recovery reliability, streamed output, latency,
and structural token/cost tracking.  Run ``run_full_bakeoff()`` to get a
side-by-side dict; ``render_markdown()`` turns it into the report.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Callable

from lumen.modes.learn.loop_registry import LOOP_CAPABILITIES
from lumen.runtime.context import UnifiedContext
from lumen.runtime.stream.bus import StreamBus
from lumen.runtime.stream.events import StreamEventType
from tests.kernel.bakeoff_fakes import (
    FakeBakeoffToolService,
    ScriptedLangChainModel,
    ScriptedOpenAIClient,
    make_ask_tool,
    make_calc_tool,
)

# ── Provider drivers ───────────────────────────────────────────────────────
# ``bakeoff_fakes`` is shared / git-tracked infra we should not special-case,
# so linear-replay and message-capture probes live here as thin subclasses
# rather than edits to that file.


class _LinearOpenAIClient(ScriptedOpenAIClient):
    """ScriptedOpenAIClient replaying steps linearly (one per LLM call), the
    same way ScriptedLangChainModel does, so sequential multi-round tool
    flows replay identically across the two providers."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    def _select_step(self, messages: list[dict[str, Any]]) -> Any:
        _ = messages  # linear replay, symmetric with the LangChain scripted model
        if not self._script:
            return "Answer."
        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return step


_LC_SEEN: list[Any] = []


class _ProbeScriptedLC(ScriptedLangChainModel):
    """ScriptedLangChainModel that also records every message batch it sees
    into the module-level ``_LC_SEEN`` (so bind_tools deep-copies still report
    the messages the graph actually passed to the model)."""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        _LC_SEEN.extend(messages)
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        _LC_SEEN.extend(messages)
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


# ── FROZEN scenario catalog ────────────────────────────────────────────────

MASTERY_TOOL = "mastery_status"


async def _async_reply() -> str:
    """Async user-reply waiter (mirrors the WS submit hook, which is async)."""
    await asyncio.sleep(0)
    return "I am 20"


def _make_mastery_tool(capture: list[str]) -> Any:
    """A deterministic mastery-status tool.  Appends the learner-state binding
    (``_mastery_path_id``) the agent loop injected into the call into *capture*
    so augment_kwargs is directly observable beyond stream events (which strip
    ``_``-prefixed private args)."""

    from lumen.runtime.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

    class MasteryStatusTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(
                name=MASTERY_TOOL,
                description="Report the learner's current mastery status for this path.",
                parameters=[
                    ToolParameter(name="topic", type="string", description="Topic to report on")
                ],
            )

        async def execute(self, **kwargs: Any) -> ToolResult:
            bound = str(kwargs.get("_mastery_path_id", "<none>"))
            capture.append(bound)
            return ToolResult(content="mastery: 60%", metadata={"bound_path": bound})

    return MasteryStatusTool()


def _make_boom_tool() -> Any:
    """A tool that always raises, for the tool-error/recovery scenario."""
    from lumen.runtime.tool_protocol import BaseTool, ToolDefinition, ToolResult

    class BoomTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(name="boom", description="Always fails.")

        async def execute(self, **kwargs: Any) -> ToolResult:
            raise RuntimeError("boom")

    return BoomTool()


@dataclass
class Scenario:
    """One frozen bake-off scenario (identical inputs for both providers)."""

    id: str
    user_message: str
    tools: list[Callable[[], Any]]
    script: list[Any]
    enabled_tools: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    wait_for_user_reply: Any = None
    conversation_history: list[dict[str, Any]] | None = None
    category: str = ""


# calc available by default in the per-side tool registry through ``register_all``.
SCENARIOS: list[Scenario] = [
    Scenario(
        id="single_tool_call",
        category="1-single-tool",
        user_message="compute 2+3",
        tools=[make_calc_tool],
        script=[{"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]}, "Result is 5."],
        enabled_tools=["calc"],
    ),
    Scenario(
        id="multi_tool_sequential",
        category="2-multi-tool",
        user_message="two computations",
        tools=[make_calc_tool],
        script=[
            {"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 1}}]},
            {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 2}}]},
            "Done.",
        ],
        enabled_tools=["calc"],
    ),
    Scenario(
        id="tool_error_recovery",
        category="3-tool-error",
        user_message="boom then calc",
        tools=[_make_boom_tool, make_calc_tool],
        script=[
            {"tool_calls": [{"name": "boom", "args": {}}]},
            {"tool_calls": [{"name": "calc", "args": {"a": 4, "b": 4}}]},
            "Recovered.",
        ],
        enabled_tools=["boom", "calc"],
    ),
    Scenario(
        id="structured_args",
        category="4-structured-args",
        user_message="compute 10+20",
        tools=[make_calc_tool],
        script=[{"tool_calls": [{"name": "calc", "args": {"a": 10, "b": 20}}]}, "30."],
        enabled_tools=["calc"],
    ),
    Scenario(
        id="streaming",
        category="5-streaming",
        user_message="stream please",
        tools=[],
        script=["This is a streamed answer with several distinct characters."],
        enabled_tools=[],
    ),
    Scenario(
        id="ask_user_interrupt_resume",
        category="6-interrupt-resume",
        user_message="ask me",
        tools=[make_ask_tool],
        script=[
            {"tool_calls": [{"name": "ask_user", "args": {"question": "How old are you?"}}]},
            "Got it, thanks.",
        ],
        enabled_tools=["ask_user"],
        wait_for_user_reply=_async_reply,
    ),
    Scenario(
        id="cancellation",
        category="7-cancellation",
        user_message="long stream",
        tools=[],
        script=["A long streaming answer with a lot of characters to allow timing."],
        enabled_tools=[],
    ),
    Scenario(
        id="long_session_continuity",
        category="8-long-session",
        user_message="continue",
        tools=[],
        script=["Continuing from what we discussed."],
        enabled_tools=[],
        conversation_history=[
            {"role": "user", "content": "Prior user question"},
            {"role": "assistant", "content": "Prior assistant answer"},
        ],
    ),
    Scenario(
        id="learn_turn",
        category="9-learn",
        user_message="teach me calculus",
        tools=[_make_mastery_tool, make_calc_tool],
        script=[
            {"tool_calls": [{"name": "mastery_status", "args": {"topic": "derivative"}}]},
            "Learner progress tracked.",
        ],
        # NB: mastery_status is NOT in enabled_tools.  Its availability is
        # the capability-owned tool surface that the provider must mount
        # (via loop_capabilities.owned_tools), mirroring a real Learn turn.
        enabled_tools=["calc"],
        metadata={"mastery_mode": True, "mastery_path_id": "path-1"},
    ),
]


@dataclass
class ProviderResult:
    """Outcome of one scenario on one provider (one rep)."""

    scenario: str
    side: str
    ok: bool = False
    completed: bool = False
    final_text: str = ""
    error: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    streamed_chars: int = 0
    n_content_events: int = 0
    n_tool_events: int = 0
    latency_s: float = 0.0
    prompts: dict[str, Any] = field(default_factory=dict)


# ── Provider drivers ───────────────────────────────────────────────────────


def _new_bus() -> StreamBus:
    return StreamBus()


def _make_ctx(
    scenario: Scenario,
    *,
    enabled_tools: list[str],
    wait_for_user_reply: Any,
) -> UnifiedContext:
    ctx = UnifiedContext(
        session_id=f"bakeoff-v1-{scenario.id}",
        user_message=scenario.user_message,
        enabled_tools=enabled_tools,
        knowledge_bases=[],
        language="en",
        metadata=dict(scenario.metadata or {}),
    )
    if scenario.conversation_history:
        ctx.conversation_history = list(scenario.conversation_history)
    if wait_for_user_reply is not None:
        ctx.metadata["wait_for_user_reply"] = wait_for_user_reply
    return ctx


async def _run_legacy(scenario: Scenario) -> ProviderResult:
    from lumen.runtime.agent_loop.providers.legacy.agentic_pipeline import AgenticChatPipeline

    tools, mastery_capture = _build_tools(scenario)
    # Loop capabilities are forwarded exactly as mode.learn does.
    client = _LinearOpenAIClient(scenario.script)
    pipeline = AgenticChatPipeline(
        language="en",
        registry=tools,
        client_factory=lambda _cfg: client,
        loop_capabilities=LOOP_CAPABILITIES,
    )
    bus = _new_bus()
    ctx = _make_ctx(
        scenario,
        enabled_tools=list(scenario.enabled_tools or []),
        wait_for_user_reply=scenario.wait_for_user_reply,
    )
    start = time.perf_counter()
    ok_run = True
    error = ""
    try:
        await pipeline.run(ctx, bus)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        ok_run = False
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start
    res = _result_from_events(
        scenario,
        "legacy",
        list(bus._history),
        latency=latency,
        error=error,
        pipeline=pipeline,
        client=client,
    )
    if ok_run:
        res.ok = bool(res.final_text.strip())
    res.prompts["mastery_bound_seen"] = list(mastery_capture)
    return res


async def _run_langchain(scenario: Scenario) -> ProviderResult:
    from lumen.agent_loop_langchain import _LangChainAgentLoopAdapter
    from tests.kernel.bakeoff_harness import run_scenario

    tools, mastery_capture = _build_tools(scenario)
    _LC_SEEN.clear()
    model = _ProbeScriptedLC(list(scenario.script))
    adapter = _LangChainAgentLoopAdapter(llm_service=None, tool_service=tools)
    start = time.perf_counter()
    sr = await run_scenario(
        adapter,
        scenario=scenario.id,
        user_message=scenario.user_message,
        enabled_tools=list(scenario.enabled_tools or []),
        metadata=dict(scenario.metadata or {}),
        wait_for_user_reply=scenario.wait_for_user_reply,
        config={"langchain_model": model},
    )
    latency = time.perf_counter() - start
    # Conversation-history continuity + system-prompt fidelity probes.
    seen = [m for m in _LC_SEEN]
    seen_text = " ".join(str(getattr(m, "content", "") or "") for m in seen)
    res = ProviderResult(
        scenario=scenario.id,
        side="langchain",
        ok=sr.ok,
        completed=sr.completed,
        final_text=sr.final_text,
        error=sr.error,
        tool_calls=list(sr.tool_calls),
        streamed_chars=sr.streamed_chars,
        n_content_events=sum(1 for e in sr.events if e.type == StreamEventType.CONTENT),
        latency_s=latency,
        prompts={
            "seen_message_types": [m.type for m in seen],
            "n_seen": len(seen),
            "system_prompt_len": len(
                str(next((m.content for m in seen if m.type == "system"), "")) or ""
            ),
            "history_carried": _history_present_text(seen_text),
            "mastery_bound_seen": list(mastery_capture),
        },
    )
    return res


def _build_tools(scenario: Scenario) -> tuple[FakeBakeoffToolService, list[str]]:
    """Build the scenario's deterministic tool registry + a capture list that
    the mastery tool records its learner-state binding into."""
    tools = FakeBakeoffToolService()
    mastery_capture: list[str] = []
    for builder in scenario.tools:
        if builder is _make_mastery_tool:
            tools.register(builder(mastery_capture))
        elif builder is _make_boom_tool:
            tools.register(builder())
        else:
            tools.register(builder())
    return tools, mastery_capture


def _history_present_text(text: str) -> bool:
    return "Prior user question" in text and "Prior assistant answer" in text


def _result_from_events(
    scenario: Scenario,
    side: str,
    events: list,
    *,
    latency: float,
    error: str = "",
    pipeline: Any = None,
    client: ScriptedOpenAIClient | None = None,
) -> ProviderResult:
    content_parts: list[str] = []
    tool_calls: list[tuple[str, dict[str, Any]]] = []
    final_text = ""
    completed = False
    for e in events:
        if e.type == StreamEventType.CONTENT:
            content_parts.append(e.content or "")
            continue
        if e.type == StreamEventType.TOOL_CALL:
            tool_calls.append((e.content or "", dict(e.metadata.get("args", {}) or {})))
            continue
        if e.type == StreamEventType.RESULT:
            final_text = str(e.metadata.get("response") or "")
            completed = bool(e.metadata.get("completed", False))
    if not final_text:
        final_text = "".join(content_parts)
    probes: dict[str, Any] = {}
    # System prompt fidelity probe (capability system block mounted?).
    if pipeline is not None and getattr(pipeline, "_last_prompt_blocks", None):
        probes["prompt_blocks"] = [getattr(b, "name", "?") for b in pipeline._last_prompt_blocks]
    if client is not None and client.calls:
        first_msgs = client.calls[0].get("kwargs", {}).get("messages", [])
        probes["first_request_has_system"] = any(m.get("role") == "system" for m in first_msgs)
        probes["n_first_request_messages"] = len(first_msgs)
        probes["history_carried"] = _history_present(first_msgs)
        probes["request_messages"] = [dict(m) for m in first_msgs]
    # Usage tracking probe (structural presence).
    if pipeline is not None:
        usage = getattr(pipeline, "usage", None)
        if usage is not None:
            probes["usage_tracked"] = True
            probes["usage_obj"] = str(type(usage).__name__)
    return ProviderResult(
        scenario=scenario.id,
        side=side,
        ok=bool(final_text.strip()) and not error,
        completed=completed,
        final_text=final_text,
        error=error,
        tool_calls=tool_calls,
        streamed_chars=sum(len(p) for p in content_parts),
        n_content_events=sum(1 for e in events if e.type == StreamEventType.CONTENT),
        n_tool_events=len(tool_calls),
        latency_s=latency,
        prompts=probes,
    )


def _history_present(messages: list[dict[str, Any]]) -> bool:
    """Whether a prior user/assistant turn from context.conversation_history
    was carried into the LLM request (long-session continuity)."""
    text = "".join(str(m.get("content") or "") for m in messages)
    return "Prior user question" in text and "Prior assistant answer" in text


# ── Scenario judges ────────────────────────────────────────────────────────


def _judge(scenario: Scenario, res: ProviderResult) -> tuple[bool, dict[str, Any]]:
    metrics: dict[str, Any] = {}
    calls = res.tool_calls
    if scenario.id in {"single_tool_call", "structured_args"}:
        expected = (
            ("calc", {"a": 2, "b": 3})
            if scenario.id == "single_tool_call"
            else ("calc", {"a": 10, "b": 20})
        )
        got = calls[0] if calls else None
        metrics["tool_selected"] = bool(got and got[0] == expected[0])
        metrics["args_correct"] = bool(got and got[1] == expected[1])
        return bool(res.final_text.strip()) and metrics["tool_selected"] and metrics[
            "args_correct"
        ] and not res.error, metrics
    if scenario.id == "multi_tool_sequential":
        metrics["tool_selected"] = [name for name, _ in calls] == ["calc", "calc"]
        metrics["args_correct"] = [args for _, args in calls] == [
            {"a": 1, "b": 1},
            {"a": 2, "b": 2},
        ]
        return len(calls) >= 2 and metrics["tool_selected"] and metrics[
            "args_correct"
        ] and not res.error, metrics
    if scenario.id == "tool_error_recovery":
        names = [name for name, _ in calls]
        metrics["recovered_after_error"] = "calc" in names and "boom" in names
        metrics["recovery_last_tool_ok"] = bool(names) and names[-1] == "calc"
        return bool(res.final_text.strip()) and metrics[
            "recovered_after_error"
        ] and not res.error, metrics
    if scenario.id == "streaming":
        metrics["streamed_incrementally"] = res.n_content_events > 1
        return bool(res.final_text.strip()) and metrics[
            "streamed_incrementally"
        ] and not res.error, metrics
    if scenario.id == "ask_user_interrupt_resume":
        metrics["tool_selected"] = bool(calls) and calls[0][0] == "ask_user"
        return metrics["tool_selected"] and bool(res.final_text.strip()) and not res.error, metrics
    if scenario.id == "cancellation":
        # Cancellation is scored as a clean stop inside a bounded window.
        return not res.error and res.completed is not True, metrics
    if scenario.id == "long_session_continuity":
        metrics["history_carried_into_request"] = bool(res.prompts.get("history_carried"))
        return metrics["history_carried_into_request"], metrics
    if scenario.id == "learn_turn":
        # Learn E2E: the mastery tool (capability-owned) must be MOUNTED and
        # called, with the learner-state binding (_mastery_path_id) applied.
        metrics["mastery_tool_mounted"] = any(name == MASTERY_TOOL for name, _ in calls)
        bound = list(res.prompts.get("mastery_bound_seen", []))
        metrics["mastery_state_bound"] = "path-1" in bound
        metrics["mastery_prompt_block"] = bool(res.prompts.get("prompt_blocks"))
        metrics["usage_tracked"] = bool(res.prompts.get("usage_tracked"))
        return bool(res.final_text.strip()) and metrics["mastery_tool_mounted"] and metrics[
            "mastery_state_bound"
        ] and not res.error, metrics
    return bool(res.final_text.strip()) and not res.error, metrics


# ── Runner ─────────────────────────────────────────────────────────────────


async def _run_cancellable(side: str, scenario: Scenario) -> ProviderResult:
    """Cancellation: start the loop, cancel after a short delay, require a
    clean (bounded) stop without a hang or an unhandled error."""
    if side == "legacy":
        run = _run_legacy(scenario)
    else:
        run = _run_langchain(scenario)
    task = asyncio.create_task(run)
    await asyncio.sleep(0.01)
    task.cancel()
    start = time.perf_counter()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.CancelledError:
        pass
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return ProviderResult(
            scenario=scenario.id, side=side, ok=False, error="cancel_cleanup_hang"
        )
    latency = time.perf_counter() - start
    res = ProviderResult(
        scenario=scenario.id, side=side, ok=True, completed=False, latency_s=latency
    )
    res.prompts["cancelled_cleanly"] = True
    return res


RUNNERS = {
    "legacy": lambda _side, scenario: _run_legacy(scenario),
    "langchain": lambda _side, scenario: _run_langchain(scenario),
}


async def run_full_bakeoff(
    sides: tuple[str, ...] = ("legacy", "langchain"), reps: int = 3
) -> dict[str, Any]:
    """Run every frozen scenario against each provider ``reps`` times.

    Returns a nested dict::

        {"reps": reps, "scenarios": {sid: {"legacy": [ProviderResult,...], "langchain": [...]}}}
    """
    report: dict[str, Any] = {"reps": reps, "scenarios": {}, "decisions": []}
    for scenario in SCENARIOS:
        per_side: dict[str, list[ProviderResult]] = {}
        for side in sides:
            runner = _run_cancellable if scenario.id == "cancellation" else RUNNERS[side]
            results: list[ProviderResult] = []
            for _i in range(reps):
                results.append(await runner(side, scenario))
            per_side[side] = results
        report["scenarios"][scenario.id] = per_side
    return report


def _best(results: list[ProviderResult]) -> ProviderResult:
    """Return the first (replay-stable baseline) result of a side."""
    return results[0] if results else ProviderResult(scenario="?", side="?")


def _side_pass(results: list[ProviderResult]) -> tuple[bool, bool]:
    """(replay-stable, any-pass) using the scenario-specific judge verdict."""
    oks = [_judge(_scenario_by_id(r.scenario), r)[0] for r in results]
    return all(oks), any(oks)


def _scenario_by_id(sid: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.id == sid:
            return scenario
    raise KeyError(sid)


def _verdict(results: list[ProviderResult]) -> tuple[bool, dict[str, Any]]:
    """Aggregate the judge metrics for the best (first) result of a side."""
    r = _best(results)
    return _judge(_scenario_by_id(r.scenario), r)


def _clip(value: Any, limit: int = 200, depth: int = 0) -> Any:
    """Compact long/nested probes (full system prompts, message dumps) so the
    markdown report stays readable while keeping the decisive signal."""
    if depth > 2:
        return type(value).__name__
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"...[+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return (
            {k: _clip(v, limit, depth + 1) for k, v in value.items()}
            if len(value) <= 8
            else {f"<{len(value)} keys>"}
        )
    if isinstance(value, (list, tuple)):
        clipped = [_clip(v, limit, depth + 1) for v in value[:4]]
        return clipped + (["..."] if len(value) > 4 else [])
    return value


def render_markdown(report: dict[str, Any], side_metrics: dict[str, Any] | None = None) -> str:
    """Render the side-by-side metric table + per-scenario detail + judges."""
    rows: list[str] = []
    rows.append("# Agent Loop Provider Bake-off v1 — Side-by-side")
    rows.append("")
    rows.append(f"- Repeats per scenario: **{report['reps']}** (replay stability)")
    rows.append(
        "- LLM / prompts / tools / material / context / machine: **identical** (deterministic fakes)"
    )
    rows.append("")
    rows.append("| Scenario | Legacy (pass) | LangChain (pass) |")
    rows.append("|---|---|---|")
    for sid, per_side in report["scenarios"].items():
        legacy_ok, _ = _side_pass(per_side.get("legacy", []))
        lc_ok, _ = _side_pass(per_side.get("langchain", []))
        rows.append(
            f"| {sid} | {'PASS' if legacy_ok else 'FAIL'} | {'PASS' if lc_ok else 'FAIL'} |"
        )
    rows.append("")
    rows.append("## Per-scenario detail")
    for sid, per_side in report["scenarios"].items():
        rows.append(f"### {sid}")
        for side in ("legacy", "langchain"):
            results = per_side.get(side, [])
            if not results:
                continue
            r = _best(results)
            verdict, metrics = _judge(_scenario_by_id(sid), r)
            ok_str = "PASS" if verdict else "FAIL"
            rows.append(
                f"- **{side}**: {ok_str} | completed={r.completed} | latency={r.latency_s:.3f}s | tool_calls={[(n, a) for n, a in r.tool_calls]} | error={r.error!r}"
            )
            if metrics:
                rows.append(f"  - metrics: {metrics}")
            if r.prompts:
                clipped = {k: _clip(v) for k, v in r.prompts.items()}
                rows.append(f"  - probes: {clipped}")
    if side_metrics:
        rows.append("")
        rows.append("## Summary metrics")
        rows.append("```")
        for k, v in side_metrics.items():
            rows.append(f"{k}: {v}")
        rows.append("```")
    return "\n".join(rows) + "\n"


__all__ = [
    "SCENARIOS",
    "ProviderResult",
    "run_full_bakeoff",
    "render_markdown",
    "_judge",
    "_side_pass",
]

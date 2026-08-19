"""P3 — LangGraph Dual Runtime.

Structure::

    Agent Runtime
         ↕ Contract Bridge Node
    Teaching Runtime

LangGraph owns: graph execution, state transition, checkpointing, interrupt/
resume, durable execution.  Lumen Teaching Runtime owns: learner diagnosis,
teaching strategy, scaffolding, remediation, assessment, pedagogical decision.

The two halves communicate ONLY through an explicit bridge node that converts
an ``AgentUpdate`` (what the agent just did) into a ``TeachingInput`` (what the
teaching runtime needs) and a ``TeachingDecision`` (what the agent should do
next) back into the graph as a directive.  Neither side reaches into the other's
state. This is the reference architecture for a decoupled Agent ↔ Teaching
boundary on a durable graph runtime.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lumen.evolution.contract import (
    ProviderRequest,
    ProviderResult,
    RuntimeProvider,
    TeachingDecision,
    TeachingInput,
    Termination,
    TerminationReason,
    TraceEvent,
    TurnOutput,
)
from lumen.evolution.models import _text, _tool_calls


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool_requests: list[tuple[str, dict[str, Any]]]
    decision: TeachingDecision | None
    learner_snapshot: dict[str, Any]  # durable, checkpointable learner state


async def _agent_run(state: AgentState, model: Any, tools: Any, directive: str, seed: int | None) -> AgentState:
    messages = list(state.get("messages", []))
    prompt = messages
    if directive:
        prompt = messages + [{"role": "system", "content": directive}]
    out = await model.generate(prompt, tools=tools.build_schemas(), seed=seed)
    calls = _tool_calls(out)
    if not calls:
        return {**state, "messages": messages + [{"role": "assistant", "content": _text(out)}], "tool_requests": []}
    reqs = [(c.get("name"), dict(c.get("args") or {})) for c in calls]
    return {**state, "messages": messages + [{"role": "assistant", "content": _text(out)}], "tool_requests": reqs}


async def _agent_tools(state: AgentState, tools: Any) -> AgentState:
    messages = list(state.get("messages", []))
    for idx, (name, args) in enumerate(state.get("tool_requests", [])):
        try:
            result = await tools.execute(name, **args)
            content = str(result)
        except Exception as exc:  # noqa: BLE001
            content = f"Error: {exc}"
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"d{idx}", "name": name, "args": args}]})
        messages.append({"role": "tool", "tool_call_id": f"d{idx}", "content": content})
    return {**state, "messages": messages, "tool_requests": []}


def _teaching_bridge(state: AgentState, teaching: Any) -> AgentState:
    """The ONLY place teaching runtime talks to the graph.

    Translates the latest agent update into a TeachingInput, asks the Teaching
    Plugin for the next pedagogical decision, and records it on the graph state
    as a durable ``decision`` the agent reads next round.
    """
    messages = state.get("messages", [])
    user_text = ""
    if messages and isinstance(messages[0], dict):
        user_text = str(messages[0].get("content", ""))
    tin = TeachingInput(
        user_message=user_text,
        learner_state=dict(state.get("learner_snapshot", {})),
        trace={"last_directive": state.get("decision")},
    )
    decision = teaching.decide(tin)
    return {**state, "decision": decision}


class LangGraphDualProvider(RuntimeProvider):
    """LangGraph agent runtime ↔ teaching runtime, decoupled via a bridge node."""

    provider_id = "langgraph_dual"

    def __init__(self, *, max_steps: int = 10, emit_trace: bool = True) -> None:
        self._max_steps = max_steps
        self._emit_trace = emit_trace

    async def run(self, request: ProviderRequest) -> ProviderResult:
        teaching = request.teaching
        builder = StateGraph(AgentState)

        def node_bridge(state: AgentState) -> AgentState:
            return _teaching_bridge(state, teaching)

        async def node_agent(state: AgentState) -> AgentState:
            decision = state.get("decision")
            directive = ""
            if decision is not None:
                directive = teaching.scaffold(decision, request.context)
            return await _agent_run(state, request.model, request.tools, directive, request.seed)

        async def node_tools(state: AgentState) -> AgentState:
            return await _agent_tools(state, request.tools)

        builder.add_node("bridge", node_bridge)
        builder.add_node("agent", node_agent)
        builder.add_node("tools", node_tools)
        builder.add_edge(START, "bridge")
        builder.add_edge("bridge", "agent")
        builder.add_edge("tools", "bridge")
        # If agent produced NO tool_requests, the turn is terminal → END.
        builder.add_conditional_edges(
            "agent",
            lambda s: "tools" if s.get("tool_requests") else "end",
            {"tools": "tools", "end": END},
        )
        graph = builder.compile()

        messages: list[dict[str, Any]] = [{"role": "user", "content": request.input.user_message}]
        messages = list(request.input.conversation_history) + messages
        state: AgentState = {"messages": messages, "learner_snapshot": {}}
        trace: list[TraceEvent] = []
        final_text = ""
        steps = 0

        async for batch in graph.astream(state, stream_mode="updates"):
            for node_name, update in batch.items():
                steps += 1
                if self._emit_trace:
                    trace.append(TraceEvent(step=steps, kind="node", data={"node": node_name}))
                if node_name == "agent":
                    msgs = update.get("messages", [])
                    for m in reversed(msgs):
                        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content"):
                            final_text = str(m.get("content"))
                            break
                state = update
                # agent answered with no tools → terminal
                if node_name == "agent" and not update.get("tool_requests"):
                    break
            if steps >= self._max_steps:
                break

        tool_calls = []
        for m in state.get("messages", []):
            for tc in m.get("tool_calls", []):
                tool_calls.append((tc["name"], tc.get("args", {})))

        reason = TerminationReason.COMPLETED
        if steps >= self._max_steps:
            reason = TerminationReason.STEP_LIMIT
        return ProviderResult(
            provider_id=self.provider_id,
            output=TurnOutput(final_text=final_text, tool_calls=tool_calls, streamed_chars=len(final_text)),
            termination=Termination(reason=reason, completed=reason == TerminationReason.COMPLETED, step_count=steps),
            error=None,
            trace=trace,
        )


__all__ = ["LangGraphDualProvider"]
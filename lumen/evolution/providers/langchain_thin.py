"""P1 — LangGraph Thin Adapter.

Structure:

    LangGraph Agent Runtime
            ↓
    Lumen Teaching Hooks / Adapter

Minimal-thin-adapter principle: the LangGraph graph is kept to its standard
agent loop (call model → dispatch tools), and Teaching is delivered *into* the
graph from outside as a pre-turn hook (a system-prompt seed + a lightweight
adapter), NOT as a graph node.  This mirrors how the real production
``AgenticChatPipeline`` consumes ``LOOP_CAPABILITIES`` (injected, not a node).

Graph topology (thin)::

    START → agent → END         (agent calls model; if tool_calls, a tools node
                                 runs them and loops back — using the standard
                                 `create_react_agent`-style tail)
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from lumen.evolution.contract import (
    ProviderRequest,
    ProviderResult,
    RuntimeProvider,
    Termination,
    TerminationReason,
    TraceEvent,
    TurnOutput,
)
from lumen.evolution.models import _text, _tool_calls


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool_requests: list[tuple[str, dict[str, Any]]]


async def _agent_node(state: AgentState, model: Any, tools: Any, seed: int | None) -> AgentState:
    messages = list(state.get("messages", []))
    out = await model.generate(messages, tools=tools.build_schemas(), seed=seed)
    calls = _tool_calls(out)
    if not calls:
        return {"messages": messages + [{"role": "assistant", "content": _text(out)}], "tool_requests": []}
    reqs = []
    for call in calls:
        name = call.get("name")
        args = dict(call.get("args") or {})
        reqs.append((name, args))
    return {
        "messages": messages + [{"role": "assistant", "content": _text(out)}],
        "tool_requests": reqs,
    }


async def _tools_node(state: AgentState, tools: Any) -> AgentState:
    messages = list(state.get("messages", []))
    reqs = list(state.get("tool_requests", []))
    for step, (name, args) in enumerate(reqs):
        try:
            result = await tools.execute(name, **args)
            content = str(result)
        except Exception as exc:  # noqa: BLE001
            content = f"Error: {exc}"
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"t{step}", "name": name, "args": args}]})
        messages.append({"role": "tool", "tool_call_id": f"t{step}", "content": content})
    return {"messages": messages, "tool_requests": []}


def _route(state: AgentState) -> Literal["tools", END]:
    return "tools" if state.get("tool_requests") else END


class LangGraphThinProvider(RuntimeProvider):
    """LangGraph thin adapter — teaching injected as a hook, not a node."""

    provider_id = "langgraph_thin"

    def __init__(self, *, max_steps: int = 10, emit_trace: bool = True) -> None:
        self._max_steps = max_steps
        self._emit_trace = emit_trace

    async def run(self, request: ProviderRequest) -> ProviderResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": request.input.user_message}]
        messages = list(request.input.conversation_history) + messages

        if request.teaching is not None:
            # Teaching hook delivered into the graph as a seed (not a node).
            from lumen.evolution.contract import TeachingInput

            decision = request.teaching.decide(
                TeachingInput(user_message=request.input.user_message, learner_state={})
            )
            scaffold = request.teaching.scaffold(decision, request.context)
            purpose = (
                f"You are teaching in mode={decision.kind.value}; strategy={decision.strategy}. "
                f"{scaffold}".strip()
            )
            messages.insert(0, {"role": "system", "content": purpose})
        else:
            messages.insert(0, {"role": "system", "content": "You are a helpful assistant."})

        builder = StateGraph(AgentState)

        async def make_agent(state: AgentState) -> AgentState:
            return await _agent_node(state, request.model, request.tools, request.seed)

        async def make_tools(state: AgentState) -> AgentState:
            return await _tools_node(state, request.tools)

        builder.add_node("agent", make_agent)
        builder.add_node("tools", make_tools)
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
        builder.add_edge("tools", "agent")
        graph = builder.compile()

        trace: list[TraceEvent] = []
        current: AgentState = {"messages": messages}
        steps = 0
        # LangGraph drives the loop; we run until the graph ends or step limit.
        final_text = ""
        async for batch in graph.astream(current, stream_mode="updates"):
            for node_name, update in batch.items():
                steps += 1
                if self._emit_trace:
                    trace.append(TraceEvent(step=steps, kind="node", data={"node": node_name}))
                current = update
                msgs = update.get("messages")
                # capture latest assistant text
                if msgs:
                    for m in reversed(msgs):
                        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content"):
                            final_text = str(m.get("content"))
                            break
                # agent produced a plain answer (no tools) → loop can stop
                if node_name == "agent" and not update.get("tool_requests"):
                    break
            if steps >= self._max_steps:
                break

        tool_calls: list[tuple[str, dict[str, Any]]] = []
        for m in current.get("messages", []):
            for tc in m.get("tool_calls", []):
                tool_calls.append((tc["name"], tc.get("args", {})))

        reason = TerminationReason.COMPLETED
        if steps >= self._max_steps:
            reason = TerminationReason.STEP_LIMIT
        return ProviderResult(
            provider_id=self.provider_id,
            output=TurnOutput(
                final_text=final_text,
                tool_calls=tool_calls,
                streamed_chars=len(final_text),
            ),
            termination=Termination(reason=reason, completed=reason == TerminationReason.COMPLETED, step_count=steps),
            error=None,
            trace=trace,
        )


__all__ = ["LangGraphThinProvider"]
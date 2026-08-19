"""P2 — LangGraph Teaching Nodes.

Teaching is promoted from a *hook* (P1) to a *first-class LangGraph node*::

    Understand
       ↓
    Teaching Policy
       ↓
    Reason / Tool
       ↓
    Assessment
       ↓
    Teaching Policy

The graph owns execution *and* the teaching stage transitions.  Teaching
decisions still come ONLY from the Teaching Plugin (the frozen Contract), never
from runtime-side hardcoded strategy — the runtime supplies the *stage*, the
plugin supplies the *decision*.
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


class TeachingState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    last_decision: TeachingDecision
    tool_requests: list[tuple[str, dict[str, Any]]]
    stage: str
    done: bool


def _understand(state: TeachingState) -> TeachingState:
    return {**state, "stage": "understand"}


def _policy(state: TeachingState, teaching: Any) -> TeachingState:
    messages = state.get("messages", [])
    user_text = ""
    if messages and isinstance(messages[0], dict):
        user_text = str(messages[0].get("content", ""))
    decision = teaching.decide(
        TeachingInput(user_message=user_text, learner_state={"stage": state.get("stage", "")})
    )
    return {**state, "last_decision": decision, "stage": "policy"}


def _reason(state: TeachingState) -> TeachingState:
    return {**state, "stage": "reason"}


def _assess(
    state: TeachingState, teaching: Any, output_holder: list[dict[str, Any]]
) -> TeachingState:
    decision = state.get("last_decision")
    if decision is not None:
        record = teaching.assess(decision, state.get("messages", []))
        output_holder.append({"decision": decision.kind.value, **record})
    return {**state, "stage": "assess"}


def _route(state: TeachingState) -> str:
    """Continue acting until the model has produced a terminal plain answer.

    Teaching Policy is consulted on every loop; the graph terminates once
    ``done`` is set (the model answered without requesting tools).
    """
    if state.get("done"):
        return END
    return "reason"


class LangGraphNodesProvider(RuntimeProvider):
    """LangGraph runtime where teaching stages are graph nodes."""

    provider_id = "langgraph_nodes"

    def __init__(
        self, *, max_steps: int = 30, max_teaching_rounds: int = 12, emit_trace: bool = True
    ) -> None:
        self._max_steps = max_steps
        self._max_teaching_rounds = max_teaching_rounds
        self._emit_trace = emit_trace

    async def run(self, request: ProviderRequest) -> ProviderResult:
        teaching = request.teaching
        output_holder: list[dict[str, Any]] = []

        builder = StateGraph(TeachingState)

        def node_understand(state: TeachingState) -> TeachingState:
            return _understand(state)

        def node_policy(state: TeachingState) -> TeachingState:
            return _policy(state, teaching)

        async def node_reason(state: TeachingState) -> TeachingState:
            messages = list(state.get("messages", []))
            seed_segment = ""
            decision = state.get("last_decision")
            if decision is not None and teaching is not None:
                seed_segment = teaching.scaffold(decision, request.context)
            model_out = await request.model.generate(
                messages + [{"role": "system", "content": seed_segment}]
                if seed_segment
                else messages,
                tools=request.tools.build_schemas(),
                seed=request.seed,
            )
            calls = _tool_calls(model_out)
            text = _text(model_out)
            new_messages = list(messages)
            if not calls:
                new_messages.append({"role": "assistant", "content": text})
                return {**state, "messages": new_messages, "tool_requests": [], "done": True}
            reqs = [(str(c.get("name")), dict(c.get("args") or {})) for c in calls]
            return {**state, "messages": new_messages, "tool_requests": reqs}

        async def node_tools(state: TeachingState) -> TeachingState:
            messages = list(state.get("messages", []))
            for idx, (name, args) in enumerate(state.get("tool_requests", [])):
                try:
                    result = await request.tools.execute(name, **args)
                    content = str(result)
                except Exception as exc:  # noqa: BLE001
                    content = f"Error: {exc}"
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"n{idx}", "name": name, "args": args}],
                    }
                )
                messages.append({"role": "tool", "tool_call_id": f"n{idx}", "content": content})
            return {**state, "messages": messages, "tool_requests": []}

        def node_assess(state: TeachingState) -> TeachingState:
            return _assess(state, teaching, output_holder)

        builder.add_node("understand", node_understand)
        builder.add_node("policy", node_policy)
        builder.add_node("reason", node_reason)
        builder.add_node("tools", node_tools)
        builder.add_node("assess", node_assess)
        builder.add_edge(START, "understand")
        builder.add_edge("understand", "policy")
        # reason: if tool_requests → tools, else → assess (terminal answer to grade)
        builder.add_conditional_edges(
            "reason",
            lambda s: "tools" if s.get("tool_requests") else "assess",
            {"tools": "tools", "assess": "assess"},
        )
        builder.add_edge("tools", "assess")
        builder.add_edge("assess", "policy")
        # policy: continue acting (reason) or terminate when done
        builder.add_conditional_edges("policy", _route, {"reason": "reason", END: END})
        graph = builder.compile()

        messages: list[dict[str, Any]] = [{"role": "user", "content": request.input.user_message}]
        messages = list(request.input.conversation_history) + messages
        trace: list[TraceEvent] = []
        final_text = ""
        steps = 0
        teaching_rounds = 0
        state: TeachingState = {"messages": messages, "done": False}

        async for batch in graph.astream(state, stream_mode="updates"):
            for node_name, update in batch.items():
                steps += 1
                if self._emit_trace:
                    trace.append(TraceEvent(step=steps, kind="node", data={"node": node_name}))
                if node_name == "reason":
                    msgs = update.get("messages", [])
                    for m in reversed(msgs):
                        if (
                            isinstance(m, dict)
                            and m.get("role") == "assistant"
                            and m.get("content")
                        ):
                            final_text = str(m.get("content"))
                            break
                if node_name == "policy":
                    teaching_rounds += 1
                state = update
            if steps >= self._max_steps or (
                node_name == "policy" and teaching_rounds >= self._max_teaching_rounds
            ):
                break

        # final text fallback
        tool_calls = []
        for m in state.get("messages", []):
            for tc in m.get("tool_calls", []):
                tool_calls.append((tc["name"], tc.get("args", {})))

        reason = TerminationReason.COMPLETED
        if steps >= self._max_steps:
            reason = TerminationReason.STEP_LIMIT
        termination = Termination(
            reason=reason, completed=reason == TerminationReason.COMPLETED, step_count=steps
        )
        return ProviderResult(
            provider_id=self.provider_id,
            output=TurnOutput(
                final_text=final_text,
                tool_calls=tool_calls,
                streamed_chars=len(final_text),
                events=output_holder,
            ),
            termination=termination,
            error=None,
            trace=trace,
            metrics={"teaching_rounds": float(teaching_rounds)},
        )


__all__ = ["LangGraphNodesProvider"]

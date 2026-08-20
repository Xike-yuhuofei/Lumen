"""Spike harness — Persistent LangGraph Checkpointer correctness validation.

This validates LangGraph's durable execution primitives as a candidate base
for a future Teaching Session Graph, **without implementing it**. It uses:

* a *real persistent* checkpointer — the production ``LumenSqliteCheckpointer``
  (SQLite file, survives the Python process), never an in-memory saver;
* the unmodified P1 ``LangGraphThinProvider`` (``lumen.evolution.providers``)
  to prove the Lumen integration path (thread identity, safe resume, no
  duplicate tool side effects across a process restart);
* a small representative interrupt-capable ``StateGraph`` to prove native
  ``interrupt()`` pause → durable checkpoint → resume-with-input → complete,
  across separate OS processes (crash via ``os._exit`` in the writer).

Cross-process results are verified by re-opening the same SQLite file from a
fresh Python process/loop — proof the execution state outlives the process.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.types import interrupt  # native LangGraph interrupt primitive


def make_checkpointer(db_path: str):
    """The production durable async checkpointer used throughout this spike."""
    from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer

    return LumenSqliteCheckpointer(db_path)

# ── Representative interrupt-capable execution graph ─────────────────────┴


class SessState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool_requests: list[tuple[str, dict[str, Any]]]
    interrupted: bool
    finished: bool
    schema_version: int


SCHEMA_VERSION = 1


def build_interrupt_graph(checkpointer: Any):
    """Typical Teaching-Session-shaped graph (pre-turn model, tool dispatch,
    native interrupt for human input), compiled with a persistent saver."""
    from langgraph.graph import END, START, StateGraph

    async def _agent(state: SessState, config) -> SessState:
        ctx = config["configurable"]["__lumen"]
        out = await ctx.model.generate(state.get("messages", []), tools=ctx.tools.build_schemas())
        calls = (out.get("tool_calls") or []) if isinstance(out, dict) else []
        msgs = state.get("messages", [])
        if calls:
            return {
                **state,
                "messages": msgs + [{"role": "assistant", "content": (out.get("content", "") if isinstance(out, dict) else out),
                                     "tool_calls": _canonical(calls)}],
                "tool_requests": calls,
            }
        return {
            **state,
            "messages": msgs + [{"role": "assistant", "content": (out.get("content", "") if isinstance(out, dict) else out)}],
            "tool_requests": [],
        }

    async def _tools(state: SessState, config) -> SessState:
        ctx = config["configurable"]["__lumen"]
        msgs = list(state.get("messages", []))
        for step, req in enumerate(state.get("tool_requests", [])):
            name = req["name"]
            args = req["args"] or {}
            content = str(await ctx.tools.execute(name, **args))
            msgs.append({"role": "tool", "tool_call_id": f"p{step}", "content": content})
        return {**state, "messages": msgs, "tool_requests": []}

    async def _human(state: SessState, config) -> SessState:
        # Native LangGraph interrupt: durably pauses; resume-with-input continues.
        reply = interrupt({"question": "learner-response-required"})
        msgs = list(state.get("messages", []))
        msgs.append({"role": "user", "content": f"[learner reply] {reply}"})
        return {**state, "messages": msgs, "interrupted": True}

    async def _finish(state: SessState, config) -> SessState:
        return {**state, "finished": True}

    def _route(state: SessState) -> str:
        if state.get("tool_requests"):
            return "tools"
        if not state.get("interrupted"):
            return "human"  # first completion asks for learner input, then ends
        return "finish"

    g = StateGraph(SessState)
    g.add_node("agent", _agent)
    g.add_node("tools", _tools)
    g.add_node("human", _human)
    g.add_node("finish", _finish)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route, {"tools": "tools", "human": "human", "finish": "finish"})
    g.add_edge("tools", "agent")
    g.add_edge("human", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


def _canonical(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"c{i}",
            "type": "function",
            "function": {"name": c.get("name"), "arguments": json.dumps(c.get("args") or {})},
        }
        for i, c in enumerate(calls)
    ]


async def await_model(model: Any, messages: list[dict], tools: Any) -> dict:
    return await model.generate(messages, tools=tools.build_schemas())


# ── Minimal scripted Model / Tool seams (framework-agnostic, Lumen-shaped) ──


class ScriptedSeam:
    """Deterministic Model + counting ToolRuntime for the representative graph."""

    def __init__(self, script: list, tool_impl: Any = None) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    async def generate(self, messages, *, tools=None, seed=None, **kw):
        step = self._script.pop(0) if self._script else "Done."
        if isinstance(step, dict) and "tool_calls" in step:
            return step
        return {"content": step}

    def build_schemas(self):
        return [{"type": "function", "function": {"name": "calc", "parameters": {"type": "object"}}}]


class CountingToolRuntime:
    """Counts every dispatch — the dedup probe across process/restart."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def build_schemas(self):
        return [{"type": "function", "function": {"name": "calc", "parameters": {"type": "object"}}}]

    async def execute(self, name, /, **kwargs):
        self.calls.append((name, kwargs))
        return f"{kwargs.get('a')} + {kwargs.get('b')} = {kwargs.get('a', 0) + kwargs.get('b', 0)}"


class _CountingModel:
    def __init__(self, script: list, tool: CountingToolRuntime) -> None:
        self._script = list(script)
        self._tool = tool

    async def generate(self, messages, *, tools=None, seed=None, **kw):
        step = self._script.pop(0) if self._script else "Done."
        if isinstance(step, dict) and "tool_calls" in step:
            return step
        return {"content": step}


# ── Shared run helpers (used by both in-process and subprocess phases) ─────


async def run_provider_op(
    db_path: str, thread: str, operation: str, resume_input: str = ""
) -> dict:
    """Drive the real P1 provider through its Start/Resume/Retry contract."""
    from lumen.evolution.contract import (
        ProviderRequest,
        RuntimeContext,
        TurnInput,
        TurnState,
    )
    from lumen.evolution.providers import LangGraphThinProvider

    tool = CountingToolRuntime()
    with make_checkpointer(db_path) as saver:
        prov = LangGraphThinProvider(max_steps=12, emit_trace=True, checkpointer=saver)
        state = TurnState()
        if thread:
            state.snapshot["execution_generation"] = thread
        req = ProviderRequest(
            input=TurnInput(user_message="compute", session_id="s", conversation_history=[]),
            state=state,
            context=RuntimeContext(language="en"),
            model=_CountingModel(
                [{"tool_calls": [{"name": "calc", "args": {"a": 1, "b": 2}}]}, "Result is 3."],
                tool,
            ),
            tools=tool,
            config={"execution_operation": operation, "resume_input": resume_input, "step_budget": 12},
        )
        res = await prov.run(req)
        return {
            "operation": state.snapshot.get("execution_operation"),
            "execution_generation": state.snapshot.get("execution_generation"),
            "completed": bool(res.termination.completed),
            "reason": getattr(res.termination.reason, "value", res.termination.reason),
            "tool_calls": len(tool.calls),
        }


async def dump_state(db_path: str, thread: str) -> dict:
    """Re-open the persistent SQLite file in a fresh loop and read the thread."""
    with make_checkpointer(db_path) as saver:
        graph = build_interrupt_graph(saver)
        cfg = {"configurable": {"thread_id": thread}}
        snap = await graph.aget_state(cfg)
        vals = snap.values if snap is not None else {}
        return {
            "has_thread": snap is not None,
            "next": list(snap.next) if snap else [],
            "schema_version": vals.get("schema_version"),
            "msg_count": len(vals.get("messages", [])),
            "finished": bool(vals.get("finished")),
        }


async def run_thin_phase(db_path: str, thread: str, *, resume: bool = False) -> dict:
    """Run the real P1 LangGraphThinProvider once with a persistent saver."""
    from lumen.evolution.contract import (
        ProviderRequest,
        RuntimeContext,
        TurnInput,
        TurnState,
    )
    from lumen.evolution.providers import LangGraphThinProvider

    tool = CountingToolRuntime()

    with make_checkpointer(db_path) as saver:
        prov = LangGraphThinProvider(max_steps=12, emit_trace=True, checkpointer=saver)
        state = TurnState()
        state.snapshot["execution_generation"] = thread
        req = ProviderRequest(
            input=TurnInput(user_message="compute", session_id="s", conversation_history=[]),
            state=state,
            context=RuntimeContext(language="en"),
            model=_CountingModel(
                [
                    {"tool_calls": [{"name": "calc", "args": {"a": 2, "b": 3}}]},
                    "Result is 5.",
                ],
                tool,
            ),
            tools=tool,
            config={"resume": resume, "step_budget": 12},
        )
        result = await prov.run(req)
        snap = await prov._graph.aget_state({"configurable": {"thread_id": thread}})
        return {
            "completed": result.termination.completed,
            "reason": getattr(result.termination.reason, "value", result.termination.reason),
            "tool_calls": len(tool.calls),
            "final_text": result.output.final_text,
            "thread": thread,
            "schema_version": (snap.values or {}).get("schema_version"),
            "persisted_messages": (snap.values or {}).get("messages", [])[:4],
        }


async def run_interrupt_phase(db_path: str, thread: str, *, phase: str, inject_reply: str = "") -> dict:
    """Run a phase of the representative interrupt graph with a persistent saver.

    * phase 'start'  — begin; the graph runs agent→tools→human (interrupt),
      returns INTERRUPTED (durably checkpointed).
    * phase 'resume' — reopen the same SQLite file, resume the thread with the
      learner's reply injected via ``Command(resume=...)``.
    """
    from langgraph.types import Command

    tool = CountingToolRuntime()
    script = [
        {"tool_calls": [{"name": "calc", "args": {"a": 4, "b": 5}}]},
        "Interim result noted; ask the learner.",
    ]
    model = _CountingModel(script, tool)

    with make_checkpointer(db_path) as saver:
        graph = build_interrupt_graph(saver)
        initial = {
            "messages": [{"role": "user", "content": "start"}],
            "tool_requests": [],
            "interrupted": False,
            "finished": False,
            "schema_version": SCHEMA_VERSION,
        }
        cfg = {
            "recursion_limit": 24,
            "configurable": {"thread_id": thread, "__lumen": type("C", (), {})()},
        }
        from types import SimpleNamespace

        cfg["configurable"]["__lumen"] = SimpleNamespace(model=model, tools=tool)

        events = []
        if phase == "start":
            async for ev in graph.astream(initial, config=cfg, stream_mode="updates"):
                events.append(dict(ev))
            # graph paused at native interrupt → checkpoint durable
            snap = await graph.aget_state(cfg)
            return {
                "phase": "start",
                "tool_calls": len(tool.calls),
                "interrupted": bool(snap.next),
                "pending": snap.next,
                "events": events,
            }
        # phase resume
        async for ev in graph.astream(
            Command(resume=inject_reply), config=cfg, stream_mode="updates"
        ):
            events.append(dict(ev))
        snap = await graph.aget_state(cfg)
        return {
            "phase": "resume",
            "execution_generation": thread,
            "tool_calls": len(tool.calls),
            "finished": bool((snap.values or {}).get("finished")),
            "messages": (snap.values or {}).get("messages", []),
            "events": events,
        }
"""C1 — Production Durable Resume Wiring through the real P1 adapter.

Drives ``_LangGraphThinAgentLoopAdapter`` (the production ``runtime.agent_loop``
entry) with a real ``LumenSqliteCheckpointer`` and a streaming fake OpenAI client,
proving the durable execution-identity seam end-to-end:

* the adapter threads ``execution_generation`` / ``execution_operation`` into the
  provider and writes ``exec_*`` termination metadata back onto the context;
* a run on an ``execution_generation`` persists a durable LangGraph thread;
* ``resume`` on the SAME generation does NOT re-dispatch completed tool work;
* ``retry`` on a NEW generation is fully isolated.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
import uuid

import pytest

from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer
from lumen.runtime.agent_loop.providers.langgraph_thin.plugin import (
    _LangGraphThinAgentLoopAdapter,
)
from lumen.runtime.context import UnifiedContext
from lumen.runtime.tool_protocol import ToolResult

# ── fake OpenAI streaming client (OpenAI-Compatible gateway shape) ────────────


def _chunk(*, content: str = "", tool_call: tuple[str, dict] | None = None, usage: Any = None):
    delta = {"content": content, "tool_calls": None}
    if tool_call:
        name, args = tool_call
        # Mirror the OpenAI wire shape the P1 model seam reads: object attributes.
        delta["tool_calls"] = [
            SimpleNamespace(
                index=0,
                function=SimpleNamespace(name=name, arguments=json.dumps(args)),
            )
        ]
    return SimpleNamespace(
        usage=usage,
        choices=[SimpleNamespace(delta=SimpleNamespace(**delta))],
    )


class _FakeStreamingClient:
    """Streams a shared, ordered script of chunk responses across generate calls."""

    def __init__(self, shared: list[list[Any]]) -> None:
        self.chat = SimpleNamespace(completions=_Completions(shared))


class _Completions:
    def __init__(self, shared: list[list[Any]]) -> None:
        self._shared = shared

    async def create(self, **kwargs: Any) -> Any:
        chunks = self._shared.pop(0) if self._shared else [_chunk(content="done")]
        async def _iter():
            for c in chunks:
                yield c
        it = _iter()
        return it


# ── fake runtime seams ───────────────────────────────────────────────────────


class _FakeToolService:
    def __init__(self) -> None:
        self.calls = 0
        self._schema = {
            "type": "function",
            "function": {"name": "MYTOOL", "parameters": {"type": "object"}},
        }

    def list_tools(self) -> list[str]:
        return ["MYTOOL"]

    def get(self, name: str) -> Any:
        return object()

    def build_openai_schemas(self, names=None) -> list[dict[str, Any]]:
        return [self._schema]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        self.calls += 1
        return ToolResult(content=f"{name} ok", success=True)


class _FakeLLMService:
    def build_openai_client(self, config: Any) -> Any:  # unused when client_factory is set
        return None


class _FakeStream:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.closed = False

    async def content(self, text, *, source=None, stage=None, metadata=None):
        self.events.append(("content", text))

    async def progress(self, text, *, source=None, stage=None, metadata=None):
        self.events.append(("progress", text))

    async def tool_call(self, name, args, *, source=None, stage=None, metadata=None):
        self.events.append(("tool_call", name))

    async def tool_result(self, name, content, *, source=None, stage=None, metadata=None):
        self.events.append(("tool_result", (name, content)))

    async def result(self, payload, *, source=None, stage=None, metadata=None):
        self.events.append(("result", payload))

    async def error(self, text, *, source=None, stage=None, metadata=None):
        self.events.append(("error", text))

    async def emit(self, event, *, source=None, stage=None, metadata=None):
        self.events.append(("emit", event))

    async def close(self):
        self.closed = True


def _adapter(tmp_path) -> tuple[_LangGraphThinAgentLoopAdapter, _FakeToolService, _FakeStream]:
    tool = _FakeToolService()
    adapter = _LangGraphThinAgentLoopAdapter(
        llm_service=_FakeLLMService(),
        tool_service=tool,
    )
    return adapter, tool, _FakeStream()


def _scripted_client_factory(shared: list[list[Any]]):
    def factory(config: Any) -> Any:
        return _FakeStreamingClient(shared)
    return factory


@pytest.fixture
def openai_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the P1 model seam onto an OpenAI-compatible (native tool-calling)
    binding so the fake streaming client is used with tools enabled."""
    import lumen.runtime.agent_loop.providers.langgraph_thin.plugin as p

    cfg = SimpleNamespace(
        binding="openai",
        model="gpt-4o-mini",
        api_key="sk-test",
        base_url=None,
        api_version=None,
        extra_headers=None,
        reasoning_effort=None,
        temperature=0.2,
    )
    monkeypatch.setattr(p, "get_llm_config", lambda: cfg)


def _context(script: list[list[Any]], *, gen: str, operation: str) -> UnifiedContext:
    ctx = UnifiedContext(
        session_id="sess-1",
        user_message="hello",
        conversation_history=[{"role": "user", "content": "hello"}],
        language="en",
    )
    ctx.metadata["turn_id"] = "turn-abc"
    return ctx


def _drive(
    adapter: _LangGraphThinAgentLoopAdapter,
    stream: _FakeStream,
    ctx: UnifiedContext,
    *,
    gen: str,
    operation: str,
    resume_input: str | None = None,
    shared: list[list[Any]],
    ckp: LumenSqliteCheckpointer,
) -> dict[str, Any]:
    async def run():
        config = {
            "execution_generation": gen,
            "execution_operation": operation,
            "client_factory": _scripted_client_factory(shared),
            "step_budget": 8,
            "checkpointer": ckp,
        }
        if resume_input is not None:
            config["resume_input"] = resume_input
        await adapter.run(context=ctx, stream=stream, language=ctx.language, **config)

    asyncio.run(run())
    return dict(ctx.metadata)


def test_start_forwarding_persists_durable_thread_and_reports_back(tmp_path, openai_llm):
    adapter, tool, stream = _adapter(tmp_path)
    db = str(tmp_path / "ckp.db")
    gen = f"gen-{uuid.uuid4().hex[:10]}"
    shared = [
        [_chunk(tool_call=("MYTOOL", {"a": 1}))],
        [_chunk(content="final answer"), _chunk(usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )],
    ]
    with LumenSqliteCheckpointer(db) as ckp:
        ctx = _context(shared, gen=gen, operation="start")
        meta = _drive(adapter, stream, ctx, gen=gen, operation="start", shared=shared, ckp=ckp)

    assert meta["execution_operation"] == "start"
    assert meta["execution_generation"] == gen
    assert meta["exec_termination"] == "completed"
    assert meta["exec_completed"] is True
    assert tool.calls == 1  # MYTOOL dispatched once during start

    # The durable checkpointer holds a real thread for this execution identity.
    with LumenSqliteCheckpointer(db) as ckp2:
        snap = ckp2.get_tuple({"configurable": {"thread_id": gen}})
        assert snap is not None, "durable thread was not persisted for the execution"


def test_resume_same_generation_does_not_redispatch(tmp_path, openai_llm):
    adapter, tool, stream = _adapter(tmp_path)
    db = str(tmp_path / "ckp.db")
    gen = f"gen-{uuid.uuid4().hex[:10]}"
    shared = [
        [_chunk(tool_call=("MYTOOL", {"a": 1}))],
        [_chunk(content="final answer"), _chunk(usage=SimpleNamespace(
            prompt_tokens=4, completion_tokens=4, total_tokens=8))],
    ]
    with LumenSqliteCheckpointer(db) as ckp:
        _drive(adapter, _FakeStream(), _context(shared, gen=gen, operation="start"),
               gen=gen, operation="start", shared=shared, ckp=ckp)
        assert tool.calls == 1
        # New adapter process/instance resumes the SAME execution identity.
        adapter2, tool2, stream2 = _adapter(tmp_path)
        meta = _drive(adapter2, stream2, _context([], gen=gen, operation="resume"),
                      gen=gen, operation="resume", resume_input="continue", shared=[], ckp=ckp)

    assert meta["execution_operation"] == "resume"
    assert meta["execution_generation"] == gen
    assert meta["exec_completed"] is True
    assert tool2.calls == 0  # completed tool dispatch NOT re-run on resume


def test_retry_is_isolated_on_new_generation(tmp_path, openai_llm):
    adapter, tool, stream = _adapter(tmp_path)
    db = str(tmp_path / "ckp.db")
    gen1 = f"gen-{uuid.uuid4().hex[:10]}"
    gen2 = f"gen-{uuid.uuid4().hex[:10]}"
    shared1 = [
        [_chunk(tool_call=("MYTOOL", {"a": 1}))],
        [_chunk(content="answer1"), _chunk(usage=None)],
    ]
    with LumenSqliteCheckpointer(db) as ckp:
        _drive(adapter, _FakeStream(), _context(shared1, gen=gen1, operation="start"),
               gen=gen1, operation="start", shared=shared1, ckp=ckp)
        assert tool.calls == 1
        # Retry: a brand-new execution identity.
        adapter2, tool2, _ = _adapter(tmp_path)
        shared2 = [
            [_chunk(tool_call=("MYTOOL", {"a": 9}))],
            [_chunk(content="answer2"), _chunk(usage=None)],
        ]
        meta = _drive(adapter2, _FakeStream(), _context(shared2, gen=gen2, operation="retry"),
                      gen=gen2, operation="retry", shared=shared2, ckp=ckp)

    assert meta["execution_operation"] == "retry"
    assert meta["execution_generation"] != gen1  # isolated from the original
    assert tool2.calls == 1  # isolated attempt re-runs its own work
    with LumenSqliteCheckpointer(db) as ckp3:
        # Both the original and the retry's ACTUAL durable threads are present.
        assert ckp3.get_tuple({"configurable": {"thread_id": gen1}}) is not None
        assert (
            ckp3.get_tuple(
                {"configurable": {"thread_id": meta["execution_generation"]}}
            )
            is not None
        )
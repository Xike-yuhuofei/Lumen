"""Phase 6A — WS turn runtime cutover tests.

Covers the WS turn runtime routing after the legacy CapabilityRegistry /
ChatOrchestrator shell was removed:

    WS Learn turn → LumenBootstrap → resolve_mode() → mode.learn → runtime.agent_loop
    WS generic turn → runtime.agent_loop (Runtime contract)

The WS routing logic in ``TurnRuntimeManager`` is exercised through a fake
active bootstrap (attached via ``lumen.bootstrap.attach_bootstrap``) so the
routing decision and full turn lifecycle are tested without spinning up a
live LLM pipeline.  The kernel-level contract (the booted assembly resolves
``mode.learn`` and ``handle_turn`` runs through the injected
``runtime.agent_loop``) is covered by ``test_learn_plugins`` /
``test_bootstrap_phase5``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

# ═══════════════════════════════════════════════════════════════════════════
# Shared fakes
# ═══════════════════════════════════════════════════════════════════════════


async def _noop_async(*_args, **_kwargs):
    return None


def _fake_persona_service() -> SimpleNamespace:
    return SimpleNamespace(
        load_for_context=lambda name: (
            f"## Active Persona\n### Persona: {name}\n\nbody" if name else ""
        )
    )


class _FakeContextBuilder:
    """Legacy context builder stand-in (records + returns empty history)."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


class _FakeLearnService:
    """Minimal ``LearnModeService`` probe: mirrors the real adapter's
    turn behaviour (mark mastery_mode + resolve path id, then stream)."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self.captured = captured
        self.handle_turn_calls = 0

    async def handle_turn(self, context, stream) -> None:
        self.handle_turn_calls += 1
        self.captured["context"] = context
        self.captured["stream"] = stream
        context.metadata["mastery_mode"] = True
        context.metadata["mastery_path_id"] = context.metadata.get("mastery_path_id") or str(
            context.session_id
        )
        await stream.content(
            "Lesson content",
            source="mode.learn",
            metadata={"call_kind": "llm_final_response"},
        )


class _ProbeAgentLoop:
    """``runtime.agent_loop`` probe for generic turns (records the call)."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self.captured = captured
        self.run_calls = 0

    async def run(self, **kwargs) -> None:
        self.run_calls += 1
        stream = kwargs.get("stream")
        assert stream is not None
        await stream.content(
            "Chat reply",
            source="chat",
            metadata={"call_kind": "llm_final_response"},
        )


class _ProbePipeline:
    """Chat-pipeline probe for the no-kernel rollback path."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[Any] = []

    async def run(self, context, stream) -> None:
        self.calls.append(context)
        await stream.emit(
            StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Chat reply",
                metadata={"call_kind": "llm_final_response"},
            )
        )
        await stream.emit(StreamEvent(type=StreamEventType.DONE, source="chat"))


class _FakeBootstrap:
    """Active-assembly bridge stand-in for the WS runtime."""

    def __init__(
        self,
        learn_service: Any | None = None,
        agent_loop: Any | None = None,
    ) -> None:
        self._learn_service = learn_service
        self._agent_loop = agent_loop

    def learn_service(self, capability: str | None = None):
        if capability in ("mastery_path", "mastery", "mode.learn"):
            return self._learn_service
        return None

    def agent_loop_service(self):
        return self._agent_loop


def _attach_bootstrap(bootstrap: Any | None = None) -> Any | None:
    """Attach *bootstrap* to the module-level active-assembly bridge.

    Returns the previous active bootstrap so the caller can restore it.
    """
    from lumen import bootstrap as bootstrap_module

    previous = bootstrap_module.get_active_bootstrap()
    if bootstrap is None:
        bootstrap_module.detach_bootstrap()
    else:
        bootstrap_module.attach_bootstrap(bootstrap)
    return previous


def _patch_legacy_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the legacy services the turn runtime still touches, so the
    test drives the routing without a live LLM / store backend."""
    monkeypatch.setattr("lumen.shared._util.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", _FakeContextBuilder
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "## Memory\n## Preferences\n- Be concise.",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)


async def _wait_for_reply_queue(
    runtime: TurnRuntimeManager, turn_id: str, timeout: float = 2.0
) -> None:
    """Wait until the turn's ``ask_user`` reply queue is registered."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while runtime._reply_queues.get(turn_id) is None:
        if loop.time() >= deadline:
            raise AssertionError("reply queue never registered for turn")
        await asyncio.sleep(0.01)


def _learn_payload(*, capability: str, session_id: Any = None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "start_turn",
        "content": "teach me algebra",
        "session_id": session_id,
        "capability": capability,
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "persona": "",
        "memory_references": ["preferences"],
        "mastery_path_id": "path-1",
        "config": {},
        **extra,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Routing: mastery_path / mastery / mode.learn → mode.learn (WS level)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["mastery_path", "mastery", "mode.learn"])
async def test_ws_learn_names_route_to_mode_learn(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capability: str
) -> None:
    """Every Learn entry name runs the turn through ``LearnModeService`` —
    never through the legacy capability shell."""
    captured: dict[str, Any] = {}
    learn_service = _FakeLearnService(captured)
    previous = _attach_bootstrap(_FakeBootstrap(learn_service))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        session, turn = await runtime.start_turn(_learn_payload(capability=capability))
        events = []
        async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
            events.append(event)

        # LearnService.handle_turn was the turn engine.
        assert learn_service.handle_turn_calls == 1
        assert captured["context"].metadata["mastery_mode"] is True
        assert captured["context"].metadata["mastery_path_id"] == "path-1"
        assert callable(captured["context"].metadata["wait_for_user_reply"])

        # Streaming shape is identical to the legacy orchestrator path.
        assert [e["type"] for e in events if e["type"] != "session_meta"] == [
            "session",
            "content",
            "done",
        ]
        done = next(e for e in events if e["type"] == "done")
        assert done["metadata"]["status"] == "completed"

        # The answer was persisted as an assistant message.
        detail = await store.get_session_with_messages(session["id"])
        assert detail is not None
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["content"] == "Lesson content"
        persisted_turn = await store.get_turn(turn["id"])
        assert persisted_turn is not None
        assert persisted_turn["status"] == "completed"
    finally:
        _attach_bootstrap(previous)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Generic turns route through the Runtime contract (kernel booted on demand)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ws_chat_turn_uses_runtime_agent_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A generic (non-Learn) turn routes through the Plugin Kernel's
    ``runtime.agent_loop`` contract — the same Runtime entry mode.learn uses."""
    capture: dict[str, Any] = {}
    learn_service = _FakeLearnService(capture)
    probe_agent_loop = _ProbeAgentLoop(capture)
    previous = _attach_bootstrap(_FakeBootstrap(learn_service, probe_agent_loop))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hi",
                "session_id": None,
                "capability": "chat",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "persona": "",
                "config": {},
            }
        )
        async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
            pass

        # The chat turn went through runtime.agent_loop, never mode.learn.
        assert probe_agent_loop.run_calls == 1
        assert learn_service.handle_turn_calls == 0

        detail = await store.get_session_with_messages(session["id"])
        assert detail is not None
        assert detail["messages"][1]["content"] == "Chat reply"
    finally:
        _attach_bootstrap(previous)


@pytest.mark.asyncio
async def test_ws_chat_turn_fails_when_agent_loop_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When the attached assembly is broken (no ``runtime.agent_loop``
    service), the generic turn fails terminally instead of silently
    bypassing the Runtime contract."""
    previous = _attach_bootstrap(_FakeBootstrap(agent_loop=None))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        _session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hi",
                "session_id": None,
                "capability": "chat",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "persona": "",
                "config": {},
            }
        )
        events = []
        async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
            events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert error_events, "expected a terminal ERROR event"
        assert "runtime.agent_loop" in error_events[0]["content"]
        done = next(e for e in events if e["type"] == "done")
        assert done["metadata"]["status"] == "failed"

        persisted = await store.get_turn(turn["id"])
        assert persisted is not None
        assert persisted["status"] == "failed"
    finally:
        _attach_bootstrap(previous)


@pytest.mark.asyncio
async def test_ws_chat_turn_boots_kernel_on_demand(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Without an attached assembly the first turn boots the production
    assembly on demand and still runs through the kernel's
    ``runtime.agent_loop`` (the pipeline is built by the kernel's
    ``runtime.agent`` factory)."""
    from lumen.bootstrap import LumenBootstrap, get_active_bootstrap

    probe = _ProbePipeline()
    previous = _attach_bootstrap(None)
    try:
        monkeypatch.setattr(
            "deeptutor.agents.chat.agentic_pipeline.AgenticChatPipeline", lambda **kw: probe
        )
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        _session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hi",
                "session_id": None,
                "capability": "chat",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "persona": "",
                "config": {},
            }
        )
        async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
            pass

        # The kernel booted on demand and its AgentService built the pipeline.
        booted = get_active_bootstrap()
        assert isinstance(booted, LumenBootstrap)
        assert probe.calls, "turn never reached the pipeline through the kernel"
    finally:
        booted = get_active_bootstrap()
        _attach_bootstrap(previous)
        if isinstance(booted, LumenBootstrap):
            await booted.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 3. resolve_learn_service decision points
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_resolve_learn_service_with_real_kernel_attached() -> None:
    """With the real production kernel attached, the WS runtime resolves the
    real ``mode.learn`` adapter for every Learn name and nothing for chat."""
    from lumen.bootstrap import LumenBootstrap, get_active_bootstrap
    from lumen.modes.learn.plugin import _LearnModeServiceAdapter
    from lumen.runtime.agent_loop.providers.legacy.plugin import _AgentLoopServiceAdapter

    bootstrap = LumenBootstrap()
    await bootstrap.boot()
    previous = _attach_bootstrap(bootstrap)
    try:
        root = get_active_bootstrap().root
        runtime = TurnRuntimeManager(SQLiteSessionStore.__new__(SQLiteSessionStore))

        for name in ("mastery_path", "mastery", "mode.learn"):
            service = await runtime._resolve_learn_service(name)
            assert isinstance(service, _LearnModeServiceAdapter), name
            # Production Agent Loop stays the Legacy provider — not LangChain.
            assert isinstance(root.require("runtime.agent_loop"), _AgentLoopServiceAdapter)
        assert await runtime._resolve_learn_service("chat") is None
        assert await runtime._resolve_learn_service(None) is None
    finally:
        _attach_bootstrap(previous)
        await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_resolve_learn_service_boots_kernel_on_demand() -> None:
    """Without an attached assembly the first Learn resolution boots the
    production assembly and resolves the real ``mode.learn`` service."""
    from lumen.bootstrap import LumenBootstrap, get_active_bootstrap
    from lumen.modes.learn.plugin import _LearnModeServiceAdapter

    previous = _attach_bootstrap(None)
    runtime = TurnRuntimeManager(SQLiteSessionStore.__new__(SQLiteSessionStore))
    try:
        for name in ("mastery_path", "mastery", "mode.learn"):
            service = await runtime._resolve_learn_service(name)
            assert isinstance(service, _LearnModeServiceAdapter), name
        assert await runtime._resolve_learn_service("chat") is None
        assert await runtime._resolve_learn_service(None) is None
        assert isinstance(get_active_bootstrap(), LumenBootstrap)
    finally:
        booted = get_active_bootstrap()
        _attach_bootstrap(previous)
        if isinstance(booted, LumenBootstrap):
            await booted.shutdown()


@pytest.mark.asyncio
async def test_resolve_agent_loop_service_with_real_kernel_attached() -> None:
    """With the real production kernel attached, the WS runtime resolves the
    real ``runtime.agent_loop`` adapter (the Legacy provider) for generic
    turns."""
    from lumen.bootstrap import LumenBootstrap
    from lumen.runtime.agent_loop.providers.legacy.plugin import _AgentLoopServiceAdapter

    bootstrap = LumenBootstrap()
    await bootstrap.boot()
    previous = _attach_bootstrap(bootstrap)
    try:
        runtime = TurnRuntimeManager(SQLiteSessionStore.__new__(SQLiteSessionStore))
        service = await runtime._resolve_agent_loop_service()
        # Production Agent Loop stays the Legacy provider — not LangChain.
        assert isinstance(service, _AgentLoopServiceAdapter)
    finally:
        _attach_bootstrap(previous)
        await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_resolve_agent_loop_service_boots_kernel_on_demand() -> None:
    """Without an attached assembly the first generic-turn resolution boots
    the production assembly and resolves the real ``runtime.agent_loop``
    (the Legacy provider)."""
    from lumen.bootstrap import LumenBootstrap, get_active_bootstrap
    from lumen.runtime.agent_loop.providers.legacy.plugin import _AgentLoopServiceAdapter

    previous = _attach_bootstrap(None)
    runtime = TurnRuntimeManager(SQLiteSessionStore.__new__(SQLiteSessionStore))
    try:
        service = await runtime._resolve_agent_loop_service()
        assert isinstance(service, _AgentLoopServiceAdapter)
        assert isinstance(get_active_bootstrap(), LumenBootstrap)
    finally:
        booted = get_active_bootstrap()
        _attach_bootstrap(previous)
        if isinstance(booted, LumenBootstrap):
            await booted.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Lifecycle: session create / resume, streaming, ask_user, cancellation,
#    error handling, disposal
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_learn_turn_session_resume_and_ask_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A Learn session is created once and resumed across turns; ``ask_user``
    pause-resume (``wait_for_user_reply``) works through the WS runtime."""
    captured: dict[str, Any] = {}

    class AskOnceLearnService:
        """Ask via ``wait_for_user_reply`` only on the first turn; stream
        content directly on later turns (mirrors a learner who already
        answered on the first turn)."""

        def __init__(self) -> None:
            self.turn_count = 0
            self.captured = captured

        async def handle_turn(self, context, stream) -> None:
            self.turn_count += 1
            context.metadata["mastery_mode"] = True
            if self.turn_count == 1:
                reply = await context.metadata["wait_for_user_reply"]()
                captured["learner_reply"] = reply
                await stream.content(
                    f"Good answer: {reply.get('text', '')}",
                    source="mode.learn",
                    metadata={"call_kind": "llm_final_response"},
                )
                return
            await stream.content(
                "Lesson content",
                source="mode.learn",
                metadata={"call_kind": "llm_final_response"},
            )

    previous = _attach_bootstrap(_FakeBootstrap(AskOnceLearnService()))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        # Turn 1 creates the session and runs through mode.learn.
        session, turn1 = await runtime.start_turn(_learn_payload(capability="mode.learn"))
        # Wait until the ask_user reply queue is registered, then simulate the
        # frontend answering the pause.
        await _wait_for_reply_queue(runtime, turn1["id"])
        assert await runtime.submit_user_reply(turn1["id"], "x^2") is True
        events = []
        async for event in runtime.subscribe_turn(turn1["id"], after_seq=0):
            events.append(event)
        assert captured["learner_reply"]["text"] == "x^2"
        done = next(e for e in events if e["type"] == "done")
        assert done["metadata"]["status"] == "completed"

        # Turn 2 resumes the same session (same session_id) through mode.learn.
        session2, turn2 = await runtime.start_turn(
            _learn_payload(capability="mastery", session_id=session["id"])
        )
        async for _event in runtime.subscribe_turn(turn2["id"], after_seq=0):
            pass

        assert session2["id"] == session["id"]
        detail = await store.get_session_with_messages(session["id"])
        assert detail is not None
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
        assert detail["messages"][3]["content"] == "Lesson content"
    finally:
        _attach_bootstrap(previous)


@pytest.mark.asyncio
async def test_learn_turn_cancellation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Cancelling a running Learn turn stops the underlying mode.learn turn
    and persists the cancelled status."""
    cancelled = False
    entered = asyncio.Event()

    class BlockingLearnService:
        async def handle_turn(self, context, stream) -> None:
            nonlocal cancelled
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled = True
                raise

    previous = _attach_bootstrap(_FakeBootstrap(BlockingLearnService()))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        _session, turn = await runtime.start_turn(_learn_payload(capability="mastery_path"))
        # Wait until mode.learn actually entered the blocking turn so the
        # cancellation reaches the running agent loop.
        await asyncio.wait_for(entered.wait(), timeout=2.0)
        assert await runtime.cancel_turn(turn["id"]) is True
        assert cancelled is True

        persisted = await store.get_turn(turn["id"])
        assert persisted is not None
        assert persisted["status"] == "cancelled"
    finally:
        _attach_bootstrap(previous)


@pytest.mark.asyncio
async def test_learn_turn_error_is_terminal_and_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A mode.learn failure surfaces as a terminal ERROR + failed status."""

    class FailingLearnService:
        async def handle_turn(self, context, stream) -> None:
            raise RuntimeError("learning engine exploded")

    previous = _attach_bootstrap(_FakeBootstrap(FailingLearnService()))
    try:
        _patch_legacy_runtime(monkeypatch)

        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)

        _session, turn = await runtime.start_turn(_learn_payload(capability="mode.learn"))
        events = []
        async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
            events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert error_events, "expected a terminal ERROR event"
        assert "learning engine exploded" in error_events[0]["content"]
        done = next(e for e in events if e["type"] == "done")
        assert done["metadata"]["status"] == "failed"

        persisted = await store.get_turn(turn["id"])
        assert persisted is not None
        assert persisted["status"] == "failed"
        assert "learning engine exploded" in (persisted.get("error") or "")
    finally:
        _attach_bootstrap(previous)


@pytest.mark.asyncio
async def test_active_bootstrap_attach_detach_roundtrip() -> None:
    """attach_bootstrap / detach_bootstrap guard the module-level bridge used
    by the WS runtime."""
    from lumen.bootstrap import get_active_bootstrap

    previous = _attach_bootstrap(_FakeBootstrap(object()))
    try:
        assert get_active_bootstrap() is not None
    finally:
        _attach_bootstrap(previous)
    assert get_active_bootstrap() is previous

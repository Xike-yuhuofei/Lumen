"""C1/F2 — turn telemetry outcome alignment tests.

The agent loop may resolve a turn failure *internally* — emitting a terminal
``ERROR`` + ``DONE`` on the stream bus without raising into ``_run_turn``.
Prior to the C1/F2 fix the persisted turn was marked ``failed`` while the
turn-span status stayed ``completed`` and ``turn.completed`` was incremented,
over-stating the turn-level success SLI.

These tests drive a real ``TurnRuntimeManager`` turn with such an agent loop
and assert that the turn-span status and the ``turn.{outcome}`` counter are
driven by the SAME status that was persisted (``failed``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lumen.runtime.session.sqlite_store import SQLiteSessionStore
from lumen.runtime.session.turn_runtime import TurnRuntimeManager
from lumen.runtime.stream.events import StreamEvent, StreamEventType
from lumen.shared._util.observability import (
    NoopBackend,
    get_metrics,
    register_exporter,
    reset_metrics,
    set_backend,
    unregister_all,
)


async def _noop_async(*_args, **_kwargs):
    return None


class _SpanRecorder:
    """Fake exporter that records the finished spans handed out by dispatch."""

    def __init__(self) -> None:
        self.spans: list = []

    def export_span(self, span) -> bool:
        self.spans.append(span)
        return True

    def export_metrics(self, snapshot) -> bool:
        return True

    def flush(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass


def _fake_persona_service() -> SimpleNamespace:
    return SimpleNamespace(load_for_context=lambda name: "")


def _install_fakes(monkeypatch: pytest.MonkeyPatch, pipeline_cls) -> None:
    class _FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            on_event = kwargs.get("on_event")
            if on_event is not None:
                await on_event(
                    StreamEvent(
                        type=StreamEventType.PROGRESS,
                        source="context",
                        stage="summarizing",
                        content="summarize context",
                    )
                )
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    monkeypatch.setattr("lumen.shared._util.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr("lumen.runtime.session.context_builder.ContextBuilder", _FakeContextBuilder)
    monkeypatch.setattr(
        "lumen.runtime.agent_loop.providers.legacy.agentic_pipeline.AgenticChatPipeline",
        pipeline_cls,
    )
    monkeypatch.setattr(
        "lumen.shared._util.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr("lumen.shared._util.persona.get_persona_service", _fake_persona_service)


class _InternallyFailingPipeline:
    """Agent loop that resolves failure internally: terminal ERROR + DONE."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def run(self, context, stream):
        await stream.error(
            "provider unavailable",
            source="chat",
            metadata={"turn_terminal": True, "status": "failed"},
        )
        await stream.emit(
            StreamEvent(type=StreamEventType.DONE, source="chat", metadata={"status": "failed"})
        )


@pytest.mark.asyncio
async def test_agent_loop_internal_failure_aligns_turn_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    set_backend(NoopBackend())
    reset_metrics()
    recorder = _SpanRecorder()
    register_exporter("test-recorder", recorder)
    try:
        store = SQLiteSessionStore(tmp_path / "chat_history.db")
        runtime = TurnRuntimeManager(store)
        _install_fakes(monkeypatch, _InternallyFailingPipeline)

        session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hello",
                "session_id": None,
                "capability": None,
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
            }
        )
        async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
            pass

        # Persisted turn state is the durable source of truth.
        persisted = await store.get_turn(turn["id"])
        assert persisted is not None
        assert persisted["status"] == "failed"
        assert "provider unavailable" in str(persisted.get("error") or "")

        # Telemetry must follow the persisted outcome (C1/F2).
        snap = get_metrics().snapshot()
        assert snap.counters.get("turn.failed", 0) >= 1
        assert snap.counters.get("turn.completed", 0) == 0

        turn_spans = [s for s in recorder.spans if s.name == "turn"]
        assert turn_spans, "no turn span was exported"
        assert turn_spans[0].attrs.get("status") == "failed"
    finally:
        unregister_all()
        reset_metrics()

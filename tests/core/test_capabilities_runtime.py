"""Runtime tests for built-in capabilities under the unified framework."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.capability import ChatCapability
from deeptutor.agents.visualize.capability import VisualizeCapability
import deeptutor.agents.visualize.pipeline as visualize_pipeline
from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES


def _install_module(
    monkeypatch: pytest.MonkeyPatch, fullname: str, **attrs: Any
) -> types.ModuleType:
    parts = fullname.split(".")
    for idx in range(1, len(parts)):
        pkg_name = ".".join(parts[:idx])
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, pkg_name, pkg)
            if idx > 1:
                parent = sys.modules[".".join(parts[: idx - 1])]
                # monkeypatch (not raw setattr) so the parent package's
                # attribute is restored on teardown and never leaks a fake
                # submodule into later tests.
                monkeypatch.setattr(parent, parts[idx - 1], pkg, raising=False)

    module = types.ModuleType(fullname)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, fullname, module)
    if len(parts) > 1:
        parent = sys.modules[".".join(parts[:-1])]
        monkeypatch.setattr(parent, parts[-1], module, raising=False)
    return module


async def _collect_events(run_coro) -> list[StreamEvent]:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await run_coro(bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


def test_builtin_capability_registry_covers_documented_capabilities() -> None:
    assert set(BUILTIN_CAPABILITY_CLASSES) == {
        "chat",
        "visualize",
        "mastery_path",
    }


@pytest.mark.asyncio
async def test_chat_capability_streams_content_and_tool_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakePipeline:
        def __init__(self, language: str = "en") -> None:
            captured["pipeline_init"] = {"language": language}

        async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
            captured["process"] = {
                "message": f"{context.user_message}\nWeb fetch result",
                "enabled_tools": list(context.enabled_tools or []),
            }
            await stream.tool_call(
                "web_fetch",
                {"url": "https://example.com"},
                source="chat",
                stage="acting",
            )
            await stream.sources(
                [
                    {"type": "rag", "kb_name": "demo-kb", "content": "grounding"},
                    {"type": "web", "url": "https://example.com", "title": "Example"},
                ],
                source="chat",
                stage="responding",
            )
            await stream.content("assistant output", source="chat", stage="responding")

    monkeypatch.setattr("deeptutor.agents.chat.capability.AgenticChatPipeline", FakePipeline)

    context = UnifiedContext(
        user_message="analyze triangle",
        enabled_tools=["rag", "web_search", "web_fetch"],
        knowledge_bases=["demo-kb"],
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="img.png")],
    )

    capability = ChatCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert any(event.type == StreamEventType.TOOL_CALL for event in events)
    assert any(event.type == StreamEventType.SOURCES for event in events)
    assert any(
        event.type == StreamEventType.CONTENT and "assistant output" in event.content
        for event in events
    )
    assert "Web fetch result" in captured["process"]["message"]


# Legacy tests for the AgentCoordinator-based custom + mimic paths were
# removed when those code paths were deleted in the Phase A → C quiz
# refactor. New-pipeline coverage lives in
# ``tests/agents/question/test_pipeline.py`` (plan parsing, payload
# normalization, templates_override / mimic flow, structured emission,
# tool wiring, history loader, etc.). The ``deep_question`` capability
# itself was pruned in the pre-plugin cleanup — question generation is
# now driven by the BookEngine quiz block via ``AgentCoordinator``.


@pytest.mark.asyncio
async def test_visualize_capability_passes_attachments_to_analysis_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeAnalysis:
        render_type = "svg"
        description = "A diagram"
        data_description = "diagram data"

        def model_dump(self) -> dict[str, Any]:
            return {
                "render_type": self.render_type,
                "description": self.description,
                "data_description": self.data_description,
            }

    class FakeVisualizePipeline:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs

        async def run_analysis(self, **kwargs: Any) -> FakeAnalysis:
            captured["analysis"] = kwargs
            return FakeAnalysis()

        async def run_code_generation(self, **kwargs: Any) -> str:
            captured["code_generation"] = kwargs
            # Valid per validate_visualization (well-formed XML + camelCase
            # viewBox), so the capability takes the no-repair path.
            return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'

    monkeypatch.setattr(
        visualize_pipeline,
        "VisualizePipeline",
        FakeVisualizePipeline,
    )
    _install_module(
        monkeypatch,
        "deeptutor.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        user_message="make a figure",
        active_capability="visualize",
        config_overrides={"render_mode": "svg"},
        language="en",
        attachments=[Attachment(type="image", base64="ZmFrZQ==", filename="figure.png")],
    )

    capability = VisualizeCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert captured["analysis"]["attachments"][0].filename == "figure.png"
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["render_type"] == "svg"

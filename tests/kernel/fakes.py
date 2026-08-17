"""Test-only fake runtime providers (Phase 2).

These classes exist only for tests; the shipped package stays lean.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.contract import LLMService
from lumen.shared.contract import KnowledgeRetrievalService, RetrievalResult


class _FakeDelta:
    content: str | None = None
    reasoning_content: str | None = None


class _FakeChoice:
    delta = _FakeDelta()
    finish_reason: str | None = None


class _FakeChunk:
    choices: list[_FakeChoice] = []
    usage: Any = None


class _FakeChatCompletions:
    """Async iterable stream of chunks mimicking ``chat.completions.create``."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._call_count = 0

    async def create(self, **kwargs: Any) -> AsyncIterator[Any]:
        text = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1

        async def _stream():
            for i, char in enumerate(text):
                chunk = _FakeChunk()
                choice = _FakeChoice()
                choice.delta = _FakeDelta()
                choice.delta.content = char
                if i == len(text) - 1:
                    choice.finish_reason = "stop"
                chunk.choices = [choice]
                yield chunk
                await asyncio.sleep(0)

        return _stream()


class _FakeLLMClient:
    """Minimal OpenAI-compatible client stub returning canned responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._completions = _FakeChatCompletions(responses or ["This is a fake response."])

    @property
    def chat(self) -> "_FakeClientChat":
        return _FakeClientChat(self._completions)


class _FakeClientChat:
    def __init__(self, completions: _FakeChatCompletions) -> None:
        self.completions = completions


class FakeLLMService(LLMService):
    """A fake LLM provider for tests — returns canned text responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["This is a fake response."]

    def build_openai_client(self, config: Any) -> Any:
        return _FakeLLMClient(responses=self._responses)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        return self._responses[0]


class FakeLLMPlugin(Plugin):
    """Declares ``runtime.llm`` so it can replace the real LLM via profile
    binding without touching the agent-loop consumer."""

    manifest = PluginManifest(id="llm.fake", provides=["runtime.llm"])

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["This is a fake response."]

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("runtime.llm", FakeLLMService(responses=self._responses))


class FakeRetrievalService(KnowledgeRetrievalService):
    """A fake RAG provider for tests — returns canned retrieval content."""

    def __init__(self, content: str = "fake retrieval result") -> None:
        self._content = content
        self.searches: list[tuple[str, str]] = []

    async def search(self, query: str, kb_name: str, **kwargs: Any) -> RetrievalResult:
        self.searches.append((query, kb_name))
        return RetrievalResult(content=self._content, sources=[{"title": "fake"}])

    async def initialize(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        return True

    async def add_documents(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        return True


class FakeRetrievalPlugin(Plugin):
    """Declares ``knowledge.retrieval`` so it can replace the real RAG via
    profile binding without touching the consumer."""

    manifest = PluginManifest(id="retrieval.fake", provides=["knowledge.retrieval"])

    def __init__(self, content: str = "fake retrieval result") -> None:
        self._content = content

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("knowledge.retrieval", FakeRetrievalService(content=self._content))

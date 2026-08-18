"""Runtime adapter plugin — bridge existing ``lumen.shared._util.llm``
facades into the Plugin Kernel via :class:`LLMService`."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.llm.contract import LLMService


class _LLMServiceAdapter(LLMService):
    """Wraps ``deeptutor.core.agentic.client.build_openai_client`` for the
    OpenAI-compatible client handle, and ``lumen.shared._util.llm.factory``
    for plain completion."""

    def build_openai_client(self, config: Any) -> Any:
        from deeptutor.core.agentic.client import build_openai_client

        return build_openai_client(config)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        from lumen.shared._util.llm import factory as llm_factory

        prompt = messages[-1]["content"] if messages else ""
        return await llm_factory.complete(
            prompt=prompt,
            model=model or "",
            messages=messages,
            **kwargs,
        )


class LLMPlugin(Plugin):
    """Provide the LLM client facade as ``runtime.llm``."""

    manifest = PluginManifest(id="runtime.llm", provides=["runtime.llm"])

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("runtime.llm", _LLMServiceAdapter())

"""Runtime adapter plugin — bridge existing ``deeptutor`` agent pipeline
factory into the Plugin Kernel via :class:`AgentService`."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.contract import AgentService, LLMService, PromptService, ToolService


class _AgentServiceAdapter(AgentService):
    """Factory for the existing ``AgenticChatPipeline``.

    The ``runtime.tools`` service is injected as the pipeline's ``registry``
    (a ``ToolLookup``) through the constructor — no post-hoc reassignment.
    """

    def __init__(
        self,
        tool_service: ToolService,
        prompt_service: PromptService,
        llm_service: LLMService,
    ) -> None:
        self._tool_service = tool_service
        self._prompt_service = prompt_service
        self._llm_service = llm_service

    async def create_pipeline(self, language: str = "en", **config: Any) -> Any:
        from lumen.runtime.agent_loop.providers.legacy.agentic_pipeline import (
            AgenticChatPipeline,
        )

        if "registry" not in config:
            config["registry"] = self._tool_service
        return AgenticChatPipeline(language=language, **config)


class AgentPlugin(Plugin):
    """Provide the agent pipeline factory as ``runtime.agent``."""

    manifest = PluginManifest(
        id="runtime.agent",
        provides=["runtime.agent"],
        requires=["runtime.tools", "runtime.prompt", "runtime.llm"],
    )

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide(
            "runtime.agent",
            _AgentServiceAdapter(
                tool_service=ctx.require("runtime.tools"),
                prompt_service=ctx.require("runtime.prompt"),
                llm_service=ctx.require("runtime.llm"),
            ),
        )

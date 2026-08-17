"""Runtime adapter plugin — bridge existing ``deeptutor`` agent loop runner
into the Plugin Kernel via :class:`AgentLoopService` (legacy provider)."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.agent_loop.contract import AgentLoopService
from lumen.runtime.contract import AgentService, LLMService


class _AgentLoopServiceAdapter(AgentLoopService):
    """Runner that composes the existing ``AgenticChatPipeline`` +
    ``AgentLoop`` and runs one turn.

    The only injected seam is the LLM client: the pipeline accepts a
    ``client_factory`` constructor hook, and this adapter wires it to the
    ``runtime.llm`` contract so a bound fake provider is used without
    touching the loop itself.
    """

    def __init__(self, agent_service: AgentService, llm_service: LLMService) -> None:
        self._agent_service = agent_service
        self._llm_service = llm_service

    async def run(
        self,
        *,
        context: Any,
        stream: Any,
        language: str = "en",
        **config: Any,
    ) -> None:
        if "client_factory" not in config:
            config["client_factory"] = self._llm_service.build_openai_client
        pipeline = await self._agent_service.create_pipeline(language=language, **config)
        await pipeline.run(context, stream)


class AgentLoopPlugin(Plugin):
    """Provide the agent loop runner as ``runtime.agent_loop``."""

    manifest = PluginManifest(
        id="runtime.agent_loop",
        provides=["runtime.agent_loop"],
        requires=[
            "runtime.agent",
            "runtime.session",
            "runtime.llm",
            "runtime.tools",
            "runtime.prompt",
        ],
    )

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide(
            "runtime.agent_loop",
            _AgentLoopServiceAdapter(
                agent_service=ctx.require("runtime.agent"),
                llm_service=ctx.require("runtime.llm"),
            ),
        )

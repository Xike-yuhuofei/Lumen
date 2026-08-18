"""``mode.learn`` plugin — the plugin-kernel path to mastery-based tutoring.

The teaching stack is owned by this package (``lumen/modes/learn/``); the turn
runs through the injected ``runtime.agent_loop`` service and learner state is
read/written through the mode's own ``LearningService`` + ``LearningStore``
(``application.service`` / ``adapters.storage``).

Since Phase 5, the shared services resolved from the context are forwarded
into the agent pipeline via constructor injection (no monkey patching, no
service-locator-as-default): the pipeline uses ``knowledge.sources`` /
``memory`` / ``notebook`` / ``knowledge.retrieval`` when provided.
"""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.modes.learn.contract import LearnModeService


def _progress_dict(progress: Any) -> dict[str, Any]:
    dump = getattr(progress, "model_dump", None)
    return dump() if callable(dump) else dict(progress)


class _LearnModeServiceAdapter(LearnModeService):
    """Thin adapter over the existing learning engine + injected services.

    Dependencies arrive via constructor injection from the plugin context —
    the plugin never instantiates RAG / memory / notebook / LLM providers.
    """

    def __init__(
        self,
        agent_loop: Any,
        store: Any | None = None,
        *,
        memory_service: Any | None = None,
        notebook_service: Any | None = None,
        knowledge_sources: Any | None = None,
        knowledge_retrieval: Any | None = None,
        tools_service: Any | None = None,
        llm_service: Any | None = None,
    ) -> None:
        self._agent_loop = agent_loop
        self._store = store
        self._memory_service = memory_service
        self._notebook_service = notebook_service
        self._knowledge_sources = knowledge_sources
        self._knowledge_retrieval = knowledge_retrieval
        self._tools_service = tools_service
        self._llm_service = llm_service

    # -- learner state (existing lumen.modes.learn engine) -----------------

    def _ensure_store(self) -> Any:
        if self._store is None:
            from lumen.modes.learn.adapters.storage import LearningStore

            self._store = LearningStore()
        return self._store

    def _service(self) -> Any:
        from lumen.modes.learn.application.service import LearningService

        return LearningService(self._ensure_store())

    async def start(self, path_id: str) -> dict[str, Any]:
        progress = self._service().get_or_create(path_id)
        return _progress_dict(progress)

    async def resume(self, path_id: str) -> dict[str, Any] | None:
        progress = self._ensure_store().load(path_id)
        return _progress_dict(progress) if progress is not None else None

    async def get_state(self, path_id: str) -> dict[str, Any]:
        progress = self._ensure_store().load(path_id)
        return _progress_dict(progress) if progress is not None else {}

    # -- turn handling (existing mastery mode, driven by injected agent loop)

    def _pipeline_deps(self) -> dict[str, Any]:
        """Constructor-injected dependencies forwarded to the agent pipeline.

        All shared services the mode.learn contract declares are passed
        through as constructor arguments — the pipeline prefers them over
        the (deprecated) global registry fallbacks.
        """
        deps: dict[str, Any] = {}
        if self._memory_service is not None:
            deps["memory_service"] = self._memory_service
        if self._notebook_service is not None:
            deps["notebook_service"] = self._notebook_service
        if self._knowledge_sources is not None:
            deps["knowledge_sources"] = self._knowledge_sources
        if self._knowledge_retrieval is not None:
            deps["knowledge_retrieval"] = self._knowledge_retrieval
        if self._tools_service is not None:
            deps["registry"] = self._tools_service
        if self._llm_service is not None:
            deps["client_factory"] = self._llm_service.build_openai_client
        return deps

    async def handle_turn(self, context: Any, stream: Any) -> None:
        # The path id is resolved by mode.learn itself; the turn then flows
        # through the injected runtime.agent_loop (which resolves llm/tools via
        # contracts), so mode.learn never depends on the legacy capability layer.
        from lumen.modes.learn.adapters.learner_path import resolve_learn_path_id

        context.metadata["mastery_mode"] = True
        context.metadata["mastery_path_id"] = resolve_learn_path_id(context)
        await self._agent_loop.run(
            context=context,
            stream=stream,
            language=context.language,
            **self._pipeline_deps(),
        )


class ModeLearnPlugin(Plugin):
    """Provide mastery tutoring as ``mode.learn``.

    Depends only on service contracts — the agent loop (runtime) plus the
    shared knowledge / memory / notebook contracts.  All dependencies are
    resolved through the ``PluginContext``.
    """

    manifest = PluginManifest(
        id="mode.learn",
        provides=["mode.learn"],
        requires=[
            # runtime contracts
            "runtime.agent_loop",
            "runtime.session",
            "runtime.llm",
            "runtime.tools",
            # shared contracts
            "knowledge.sources",
            "knowledge.retrieval",
            "memory",
            "notebook",
        ],
    )

    async def setup(self, ctx: PluginContext) -> None:
        agent_loop = ctx.require("runtime.agent_loop")
        ctx.provide(
            "mode.learn",
            _LearnModeServiceAdapter(
                agent_loop=agent_loop,
                memory_service=ctx.require("memory"),
                notebook_service=ctx.require("notebook"),
                knowledge_sources=ctx.require("knowledge.sources"),
                knowledge_retrieval=ctx.require("knowledge.retrieval"),
                tools_service=ctx.require("runtime.tools"),
                llm_service=ctx.require("runtime.llm"),
            ),
        )

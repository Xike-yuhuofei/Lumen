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

import logging
from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.modes.learn.contract import LearnModeService

logger = logging.getLogger(__name__)


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
        # Lazy Teaching Session ↔ execution governor (C2).
        self._governor: Any = None
        # Lazy Teaching Session Graph (production default Learn teaching path).
        self._graph: Any = None

    def _session_governor(self) -> Any:
        if self._governor is None:
            from lumen.modes.learn.teaching_session import TeachingSessionGovernor

            self._governor = TeachingSessionGovernor()
        return self._governor

    def _graph_candidate(self) -> Any:
        if self._graph is None:
            from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint
            from lumen.modes.learn.graph.domain_service import TeachingGraphDomain
            from lumen.modes.learn.graph.orchestrator import TeachingSessionGraph

            self._graph = TeachingSessionGraph(
                store=self._ensure_store(),
                domain=TeachingGraphDomain(self._ensure_store()),
                checkpoint=TeachingGraphCheckpoint(),
            )
        return self._graph

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
        # The mode's loop capability (mastery tutor) rides into the pipeline
        # as data through the ``runtime.agent_loop`` contract — the runtime
        # never imports ``lumen.modes``, so the concrete capability is
        # contributed by its owning mode per turn.
        from lumen.modes.learn.loop_registry import LOOP_CAPABILITIES

        deps["loop_capabilities"] = LOOP_CAPABILITIES
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

        path_id = resolve_learn_path_id(context)
        context.metadata["mastery_mode"] = True
        context.metadata["mastery_path_id"] = path_id
        self._mount_goal_source(context, path_id)
        deps = self._pipeline_deps()

        # Teaching Session Graph is the sole production Learn teaching path
        # (Candidate A — teaching-hook — is retired, no legacy fallback).  Engage
        # the durable Teaching Session ↔ execution lifecycle only when the
        # injected runtime actually owns a durable execution identity (duck-typed
        # seam, never an import).  Other providers keep their exact single-run
        # behaviour below.
        if getattr(self._agent_loop, "supports_durable_execution", False):
            await self._handled_graph_turn(path_id, context, stream, deps)
            return

        await self._agent_loop.run(
            context=context,
            stream=stream,
            language=context.language,
            **deps,
        )

    async def _handled_graph_turn(
        self, path_id: str, context: Any, stream: Any, deps: dict[str, Any]
    ) -> None:
        """Run one turn through the Teaching Session Graph (production default).

        Owns the durable Teaching Session ↔ execution lifecycle and lets the
        graph drive the pedagogical flow, walking SNAPSHOT -> ASSESS -> DIAGNOSE
        -> DECIDE -> ACT -> COMMIT -> CONTINUE / TERMINATE and delegating only
        content / interaction to ``agent_loop``.
        """
        from lumen.modes.learn.teaching_session import map_termination_to_status

        governor = self._session_governor()
        teaching_session_id = governor.ensure_session(path_id)
        retry = bool(context.metadata.get("retry_execution", False))
        plan = governor.plan(
            teaching_session_id,
            retry=retry,
            resume_input=self._resume_input_for(context),
        )
        governor.record_start(plan)

        context.metadata["teaching_session_id"] = teaching_session_id
        context.metadata["execution_generation"] = plan.execution_generation
        context.metadata["execution_operation"] = plan.operation
        deps["execution_generation"] = plan.execution_generation
        deps["execution_operation"] = plan.operation
        if plan.resume_input is not None:
            deps["resume_input"] = plan.resume_input

        graph = self._graph_candidate()
        try:
            await graph.run_turn(
                path_id=path_id,
                teaching_session_id=teaching_session_id,
                execution_generation=plan.execution_generation,
                execution_operation=plan.operation,
                resume_input=plan.resume_input,
                context=context,
                stream=stream,
                agent_loop=self._agent_loop,
                deps=deps,
            )
        finally:
            actual_gen = str(
                context.metadata.get("execution_generation") or plan.execution_generation
            )
            if actual_gen != plan.execution_generation:
                governor.rebase_execution(
                    teaching_session_id,
                    plan.execution_generation,
                    actual_gen,
                )
            status = map_termination_to_status(
                operation=plan.operation,
                completed=bool(context.metadata.get("exec_completed")),
                termination=str(context.metadata.get("exec_termination") or ""),
            )
            governor.record_termination(teaching_session_id, actual_gen, status)

    def _resume_input_for(self, context: Any) -> str | None:
        """The reply/payload to inject when resuming a parked execution.

        ``context.conversation_history`` holds the just-arrived user message as
        its last entry; the agent loop's ``Command(resume=...)`` expects the
        value to answer the pending interrupt.  We pass the trailing user text
        when the governor decided to ``resume`` (the plan already carries
        ``resume_input`` if the caller set one explicitly; the adapter uses the
        explicit value).
        """
        hint = context.metadata.get("resume_input")
        if hint is not None:
            return str(hint)
        history = getattr(context, "conversation_history", None) or []
        if history:
            last = history[-1]
            if isinstance(last, dict) and last.get("role") == "user":
                return str(last.get("content") or "")
        return ""

    # -- learning-material discovery (knowledge space → Learn turn) ---------

    def _mount_goal_source(self, context: Any, path_id: str) -> None:
        """Bind the goal's knowledge space to the turn so the tutor can teach
        from its material.

        A first-time Learn turn carries no attached file: the material lives
        in the knowledge space the goal was created from (``source_kb``), not
        in the chat composer. That KB is injected into ``context.knowledge_bases``
        so ``rag`` / ``kb_files`` mount against it and the tutor stops telling
        the learner to upload a file that is already imported.
        """
        if not path_id:
            return
        kb = self._resolve_goal_kb(path_id)
        if not kb:
            return
        mounted = [str(name) for name in (context.knowledge_bases or []) if str(name).strip()]
        if kb not in mounted:
            mounted.append(kb)
        context.knowledge_bases = mounted

    def _resolve_goal_kb(self, path_id: str) -> str:
        """The KB backing *path_id*: the stored binding, else a name match."""
        try:
            progress = self._ensure_store().load(path_id)
        except Exception:
            logger.warning("Failed to load goal %s for KB binding", path_id, exc_info=True)
            return ""
        if progress is None:
            return ""
        source = str(progress.source_kb or "").strip()
        if source:
            return self._validate_source_kb(source)
        return self._discover_goal_kb(progress)

    def _validate_source_kb(self, source: str) -> str:
        """Drop a stale binding so a deleted KB is never advertised to the model."""
        if self._knowledge_sources is None:
            return source  # best-effort when discovery is unavailable
        try:
            known = self._knowledge_sources.list_knowledge_bases() or []
        except Exception:
            logger.debug("KB binding validation skipped", exc_info=True)
            return source
        return source if source in known else ""

    def _discover_goal_kb(self, progress: Any) -> str:
        """Legacy fallback for goals created before ``source_kb`` existed:
        find a knowledge space containing a document named after the goal.
        """
        goal_name = str(progress.goal_name or "").strip()
        if not goal_name:
            return ""
        try:
            if self._knowledge_sources is None:
                return ""
            kbs = self._knowledge_sources.list_knowledge_bases() or []
        except Exception:
            logger.debug("KB discovery skipped: no knowledge sources available", exc_info=True)
            return ""
        from lumen.shared._util.user import resolve_kb_manifest

        for kb in kbs:
            try:
                manifest = resolve_kb_manifest(kb, limit=1, pattern=goal_name)
            except Exception:
                continue
            if manifest is not None and manifest.matched:
                return str(kb)
        return ""


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
        _register_mastery_tools(ctx.require("runtime.tools"))
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


def _register_mastery_tools(tools: Any) -> None:
    """Register the mastery tools into the runtime tool registry at boot.

    The runtime registry never statically imports ``lumen.modes`` (Architecture
    Gate ``test_runtime_does_not_import_modes``): capability-owned tools are
    contributed by their owning mode through the injected ``runtime.tools``
    contract instead.
    """
    from lumen.modes.learn.chat_tools import MASTERY_TOOL_TYPES

    for tool_type in MASTERY_TOOL_TYPES:
        tools.register(tool_type())

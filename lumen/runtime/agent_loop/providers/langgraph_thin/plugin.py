"""P1 (LangGraph Thin) ``runtime.agent_loop`` provider plugin — dev Active Provider.

This adapter is the *bridge* that lets the unmodified P1
``LangGraphThinProvider`` (``lumen.evolution.providers.langchain_thin``) carry
real Lumen session workload in the dev environment.  It translates the real
runtime contracts onto the frozen evolution Provider Contract v1:

    Lumen AgentLoopService.run(context, stream, language, **config)
        │  (this adapter — thin translation, nothing re-implemented)
        ▼
    evolution ProviderRequest / ProviderResult  ──►  LangGraphThinProvider (P1)

The bridge deliberately keeps P1's guarantees intact and does NOT re-implement
the loop, scheduler, retry, checkpoint, or budget:

* model seam  — real ``runtime.llm`` OpenAI-compatible client with native tool
  calling (streamed to the bus), exposed as the frozen ``Model`` protocol;
* tool seam   — real ``runtime.tools`` ToolService, with per-turn capability
  kwarg augmentation (mode.learn mastery tools) and the ``ask_user``
  pause/resume bridge, exposed as the frozen ``ToolRuntime`` protocol;
* teaching    — real mode.learn ``MasteryLoopCapability.system_block``
  delivered as the P1 *pre-turn hook* (never a graph node), exposed as the
  frozen ``TeachingPlugin`` protocol;
* execution identity — each Lumen turn maps to one ``execution_generation`` /
  LangGraph ``thread_id`` (atomic attempt); multi-turn continuity comes from
  the Lumen session store via ``context.conversation_history``;
* observability — real ``StreamBus`` events (content / tool_call /
  tool_result / result / DONE) and the P1 termination mapped to the turn's
  terminal protocol.

Architecture gates hold: the runtime never imports ``lumen.modes`` — the
teaching capability and its tool augmentation arrive through constructor
injection / per-turn config from ``mode.learn``.
"""

from __future__ import annotations

from contextlib import suppress
import inspect
import json
import logging
from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.agent_loop.engine.client import (
    LLMClientConfig,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
)
from lumen.runtime.agent_loop.engine.usage import UsageTracker, message_content_chars
from lumen.runtime.contract import AgentLoopService, LLMService, ToolService
from lumen.runtime.stream.events import StreamEvent, StreamEventType
from lumen.runtime.stream.trace import build_trace_metadata, new_call_id
from lumen.shared._util.llm import get_llm_config
from lumen.shared._util.runtime_paths import get_path_service

logger = logging.getLogger(__name__)

#: Default step budget when the caller does not pass one (mirrors chat's 8 rounds).
DEFAULT_STEP_BUDGET = 8


# ── Model seam: real runtime.llm exposed as the frozen evolution Model ────────
# The evolution ``Model`` protocol is::
#
#     async def generate(messages, *, tools=None, seed=None, **kwargs) -> Any
#
# returning either ``{"tool_calls": [{"name", "args"}]}`` or a plain text
# string.  The P1 graph consumes it via ``lumen.evolution.models._tool_calls`` /
# ``_text``.  The adapter drives a real OpenAI-compatible streaming client
# (native tool calling), streams content chunks to the bus, and returns the
# assembled step — so real streaming UX is preserved inside P1's contract.


class _RealLumenModel:
    """Real LLM (native tool calling) exposed as the frozen ``Model`` protocol."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        stream: Any,
        source: str,
        stage: str,
        client_factory: Any | None = None,
        usage: UsageTracker | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._stream = stream
        self._source = source
        self._stage = stage
        self._client_factory = client_factory
        self._usage = usage or UsageTracker()
        cfg = get_llm_config()
        self._config = LLMClientConfig(
            binding=getattr(cfg, "binding", None) or "openai",
            model=getattr(cfg, "model", None),
            api_key=getattr(cfg, "api_key", None),
            base_url=getattr(cfg, "base_url", None),
            api_version=getattr(cfg, "api_version", None),
            extra_headers=getattr(cfg, "extra_headers", None) or None,
            reasoning_effort=getattr(cfg, "reasoning_effort", None),
        )
        self._temperature = getattr(cfg, "temperature", 0.2) or 0.2

    def _client(self) -> Any:
        factory = self._client_factory
        if factory is not None:
            return factory(self._config)
        return build_openai_client(self._config)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[Any] | None = None,
        seed: int | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = seed, kwargs
        client = self._client()
        use_tools = bool(tools) and can_use_native_tool_calling(
            binding=self._config.binding, model=self._config.model
        )
        completion_kwargs = build_completion_kwargs(
            temperature=self._temperature,
            model=self._config.model,
            max_tokens=4000,
            binding=self._config.binding,
            reasoning_effort=self._config.reasoning_effort,
        )
        call_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
            **completion_kwargs,
        }
        if use_tools:
            call_kwargs["tools"] = list(tools)
            call_kwargs["tool_choice"] = "auto"

        call_id = new_call_id("p1-model")
        meta = build_trace_metadata(
            call_id=call_id,
            phase="responding",
            label="Thinking",
            call_kind="agent_loop_round",
            trace_id=call_id,
            trace_role="response",
            trace_group="stage",
        )

        content_acc: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}
        usage_frame: Any = None

        async def _emit_content(text: str) -> None:
            if not text:
                return
            await self._stream.content(
                text,
                source=self._source,
                stage=self._stage,
                metadata={"call_id": call_id, "call_kind": "agent_loop_round"},
            )

        stream_iter = None
        try:
            stream_iter = await client.chat.completions.create(**call_kwargs)
            async for chunk in stream_iter:
                if getattr(chunk, "usage", None):
                    usage_frame = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = choices[0].delta
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    content_acc.append(delta.content)
                    await _emit_content(delta.content)
                for tc_delta in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tc_delta, "index", 0)
                    entry = tool_calls_acc.setdefault(idx, {"name": "", "arguments": ""})
                    fn = getattr(tc_delta, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            entry["name"] = entry["name"] + fn.name
                        if getattr(fn, "arguments", None):
                            entry["arguments"] = entry["arguments"] + fn.arguments
        finally:
            if stream_iter is not None:
                close = getattr(stream_iter, "close", None)
                if callable(close):
                    with suppress(Exception):
                        result = close()
                        if inspect.isawaitable(result):
                            await result

        text = "".join(content_acc)
        if self._usage is not None:
            if usage_frame is not None:
                self._usage.add_from_response(usage_frame)
            else:
                self._usage.add_estimated(
                    input_chars=sum(message_content_chars(m) for m in messages),
                    output_chars=len(text),
                )

        ordered = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())]
        calls = [entry for entry in ordered if entry.get("name")]
        if calls:
            # A tool round's preamble is *narration*: streamed live to the user
            # but excluded from the persisted answer (mirrors the legacy loop's
            # ``call_role=narration`` marker that turn_runtime filters on).
            if text:
                await self._stream.progress(
                    "",
                    source=self._source,
                    stage=self._stage,
                    metadata={
                        **meta,
                        "trace_kind": "call_status",
                        "call_state": "complete",
                        "call_role": "narration",
                    },
                )
            parsed: list[dict[str, Any]] = []
            for entry in calls:
                try:
                    args = json.loads(entry["arguments"] or "{}")
                except (ValueError, TypeError):
                    args = {}
                parsed.append({"name": entry["name"], "args": args})
            return {"tool_calls": parsed, "content": text}

        # Final (tool-less) round — the streamed content IS the answer.
        return text


# ── Tool seam: real runtime.tools exposed as the frozen ToolRuntime ───────────
# The evolution ``ToolRuntime`` protocol::
#
#     list_available() / definition(name) / build_schemas(names?) /
#     async execute(name, /, **kwargs) -> Any
#
# P1's graph calls ``tools.execute`` for every requested tool and stringifies
# the result into a ``role=tool`` message.  Real Lumen tools return
# ``ToolResult`` (``__str__`` = content), so execute returns the ToolResult
# directly.  ``ask_user`` pauses the turn via ``pause_for_user``: this bridge
# emits a ``WAIT_FOR_INPUT`` event and awaits the runtime reply waiter, then
# returns a ToolResult carrying the user's answer — keeping Lumen's
# interrupt/resume protocol intact inside P1's graph.


class _RealLumenToolRuntime:
    """Real ToolService exposed as the frozen ``ToolRuntime`` protocol."""

    def __init__(
        self,
        *,
        tool_service: ToolService,
        context: Any,
        stream: Any,
        source: str,
        stage: str,
        capability: Any | None = None,
    ) -> None:
        self._tool_service = tool_service
        self._context = context
        self._stream = stream
        self._source = source
        self._stage = stage
        self._capability = capability

    def list_available(self) -> list[str]:
        try:
            return list(self._tool_service.list_tools())
        except Exception:
            return []

    def definition(self, name: str) -> Any:
        try:
            return self._tool_service.get(name)
        except Exception:
            return None

    def build_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        try:
            return self._tool_service.build_openai_schemas(names)
        except Exception:
            return []

    def _augment_kwargs(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        out = dict(kwargs)
        cap = self._capability
        if cap is not None and callable(getattr(cap, "augment_kwargs", None)):
            out = cap.augment_kwargs(tool_name, out, self._context)
        return out

    async def _await_user_reply(self, tool_name: str, pause_payload: Any) -> str:
        payload = pause_payload if isinstance(pause_payload, dict) else {}
        await self._stream.emit(
            StreamEvent(
                type=StreamEventType.WAIT_FOR_INPUT,
                source=self._source,
                stage=self._stage,
                metadata={
                    "tool_name": tool_name,
                    "ask_user": payload,
                    "turn_paused": True,
                },
            )
        )
        waiter = (getattr(self._context, "metadata", {}) or {}).get("wait_for_user_reply")
        if not callable(waiter):
            return "[no reply waiter]"
        raw_reply = await waiter()
        if raw_reply is None:
            return "[user did not reply]"
        if isinstance(raw_reply, dict):
            return str(raw_reply.get("text") or raw_reply.get("content") or "")
        return str(raw_reply or "")

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        from lumen.runtime.tool_protocol import ToolResult

        augmented = self._augment_kwargs(name, kwargs)
        await self._stream.tool_call(
            name,
            augmented,
            source=self._source,
            stage=self._stage,
            metadata={"trace_kind": "tool_call"},
        )
        try:
            result = await self._tool_service.execute(name, **augmented)
        except Exception as exc:  # noqa: BLE001
            logger.warning("P1 tool %s failed: %s", name, exc)
            await self._stream.tool_result(
                name, str(exc)[:500], source=self._source, stage=self._stage
            )
            return ToolResult(content=f"Error: {exc}", success=False)

        pause = getattr(result, "pause_for_user", None)
        if pause:
            reply = await self._await_user_reply(name, pause)
            if isinstance(result, ToolResult):
                result = ToolResult(content=reply, metadata=result.metadata or {})
            await self._stream.tool_result(
                name,
                str(getattr(result, "content", reply) or reply)[:500],
                source=self._source,
                stage=self._stage,
            )
            return result

        await self._stream.tool_result(
            name,
            str(getattr(result, "content", result) or "")[:500],
            source=self._source,
            stage=self._stage,
        )
        return result


# ── Teaching seam: real mode.learn delivered as the P1 pre-turn hook ─────────
# P1's ``_teaching_seed`` calls ``teaching.decide(...)`` then
# ``teaching.scaffold(decision, context)`` and prepends a system message.  The
# real mastery system block (the teaching instructions) is that scaffold — the
# actual teaching *flow* (assessment / practice / review) is executed through
# the real mastery tools inside the graph.  Teaching stays a pre-turn hook,
# never a graph node (P1 boundary rule).


class _LearnTeachingPlugin:
    """Real mode.learn teaching exposed as the frozen ``TeachingPlugin``."""

    name = "mode.learn"

    def __init__(
        self,
        *,
        context: Any,
        language: str,
        capability: Any,
        prompts: dict[str, Any],
    ) -> None:
        self._context = context
        self._language = language
        self._capability = capability
        self._prompts = prompts

    def decide(self, tin: Any) -> Any:
        from lumen.evolution.contract import TeachingDecision, TeachingDecisionKind

        return TeachingDecision(kind=TeachingDecisionKind.EXPLAIN, strategy="socratic")

    def scaffold(self, decision: Any, context: Any) -> str:
        block = self._capability.system_block(
            self._context,
            language=self._language,
            prompts=self._prompts,
        )
        content = (getattr(block, "content", "") or "").strip()
        return content or ""

    def assess(self, decision: Any, output: Any) -> dict[str, Any]:
        return {}


# ── Adapter: AgentLoopService over LangGraphThinProvider (P1) ─────────────────


class _LangGraphThinAgentLoopAdapter(AgentLoopService):
    """Agent loop runner backed by the unmodified P1 LangGraphThinProvider.

    Every real Lumen contract dependency arrives via constructor injection.
    The adapter never imports ``lumen.modes`` / ``learning`` / ``teaching_core``.
    """

    #: Advertises the durable execution-identity seam (``execution_generation`` /
    #: ``execution_operation`` / ``resume_input`` + durable checkpointer and the
    #: ``exec_*`` termination report-back).  ``mode.learn`` uses this duck-typed
    #: marker (never an import) to engage its Teaching Session lifecycle only
    #: when the runtime actually owns durable resume — so the Legacy/other
    #: providers keep their exact previous behaviour.
    supports_durable_execution = True

    def __init__(
        self,
        llm_service: LLMService,
        tool_service: ToolService,
    ) -> None:
        self._llm_service = llm_service
        self._tool_service = tool_service
        # C1: durable checkpointer is created lazily on first run and cached, so
        # booting the kernel never opens a SQLite connection or writes to disk.
        # It can be overridden per-run through ``config["checkpointer"]``.
        self._checkpointer: Any = None

    def _checkpointer_for(self, config: dict[str, Any]):
        """Return a durable LangGraph checkpointer for this execution.

        ``config["checkpointer"]`` wins when provided.  Otherwise a lazily
        created :class:`LumenSqliteCheckpointer` (durable across process
        restarts) is used, rooted under the runtime workspace.  Returning
        ``None`` degrades gracefully to a non-durable (in-memory) run.
        """
        explicit = config.get("checkpointer")
        if explicit is not None:
            return explicit
        if self._checkpointer is None:
            db = config.get("checkpoint_db_path")
            if db is None:
                root = get_path_service().get_workspace_dir()
                (root / "runtime").mkdir(parents=True, exist_ok=True)
                db = root / "runtime" / "agent_loop_langgraph_thin.db"
            from lumen.evolution.providers.sqlite_checkpoint import LumenSqliteCheckpointer

            self._checkpointer = LumenSqliteCheckpointer(str(db))
        return self._checkpointer

    # ---- mode.learn wiring (injected via config, never imported) ----------

    def _active_capability(self, config: dict[str, Any], context: Any):
        caps = tuple(config.get("loop_capabilities") or ())
        for cap in caps:
            try:
                if callable(getattr(cap, "is_active", None)) and cap.is_active(context):
                    return cap
            except Exception:
                continue
        return None

    def _prompts(self, language: str) -> dict[str, Any]:
        try:
            from lumen.runtime.prompt.manager import get_prompt_manager

            return (
                get_prompt_manager().load_prompts(
                    module_name="chat",
                    agent_name="agentic_chat",
                    language="zh" if language.lower().startswith("zh") else "en",
                )
                or {}
            )
        except Exception:
            logger.debug("Failed to load agentic_chat prompts", exc_info=True)
            return {}

    async def run(
        self,
        *,
        context: Any,
        stream: Any,
        language: str = "en",
        **config: Any,
    ) -> None:
        from lumen.evolution.contract import (
            ProviderRequest,
            RuntimeContext,
            TurnInput,
            TurnState,
        )
        from lumen.evolution.providers import LangGraphThinProvider
        from lumen.runtime.stream import StreamEvent, StreamEventType

        user_message = str(getattr(context, "user_message", "") or "")
        metadata = getattr(context, "metadata", {}) or {}
        stage = "responding"
        turn_id = str(metadata.get("turn_id") or "").strip()
        mastery_mode = bool(metadata.get("mastery_mode", False))

        # ── 1. Real seams over the frozen contract ─────────────────────────
        capability = self._active_capability(config, context)
        usage = UsageTracker(model=None)

        model = _RealLumenModel(
            llm_service=self._llm_service,
            stream=stream,
            source="agent_loop.langgraph_thin",
            stage=stage,
            client_factory=config.get("client_factory"),
            usage=usage,
        )
        tools = _RealLumenToolRuntime(
            tool_service=self._tool_service,
            context=context,
            stream=stream,
            source="agent_loop.langgraph_thin",
            stage=stage,
            capability=capability,
        )
        teaching = None
        if mastery_mode and capability is not None:
            teaching = _LearnTeachingPlugin(
                context=context,
                language=language,
                capability=capability,
                prompts=self._prompts(language),
            )

        # ── 2. Build the ProviderRequest from the real UnifiedContext ──────
        conversation_history = list(getattr(context, "conversation_history", None) or [])
        step_budget = int(
            config.get("step_budget") or config.get("max_rounds") or DEFAULT_STEP_BUDGET
        )
        # C2: execution identity / lifecycle.  ``execution_generation`` is the
        # durable LangGraph thread (survives crash/resume); it is DISTINCT from
        # the per-turn ``turn_id`` and from any teaching-domain lineage key.
        # Default (no execution_generation) keeps the previous turn-id identity.
        operation = str(
            config.get("execution_operation")
            or ("resume" if config.get("resume") else "start")
        ).strip().lower() or "start"
        gen = str(config.get("execution_generation") or turn_id or f"turn-{new_call_id('p1')}")
        provider_config: dict[str, Any] = {"step_budget": step_budget}
        if operation in ("start", "resume", "retry"):
            provider_config["execution_operation"] = operation
        if operation == "resume":
            provider_config["resume"] = True
            if config.get("resume_input") is not None:
                provider_config["resume_input"] = config.get("resume_input")
        request = ProviderRequest(
            input=TurnInput(
                user_message=user_message,
                session_id=str(getattr(context, "session_id", "") or ""),
                conversation_history=conversation_history,
                metadata=dict(metadata),
            ),
            state=TurnState(turn_id=gen, snapshot={"execution_generation": gen}),
            context=RuntimeContext(language=language),
            model=model,
            tools=tools,
            teaching=teaching,
            config=provider_config,
        )

        # ── 3. Run the unmodified P1 provider with a durable checkpointer ──
        provider = LangGraphThinProvider(
            max_steps=step_budget,
            emit_trace=True,
            checkpointer=self._checkpointer_for(config),
        )
        completed = False
        final_text = ""
        try:
            result = await provider.run(request)
        except Exception as exc:  # noqa: BLE001
            logger.error("P1 agent loop failed: %s", exc, exc_info=True)
            await stream.error(
                str(exc),
                source="agent_loop.langgraph_thin",
                stage=stage,
                metadata={"turn_terminal": True, "status": "failed"},
            )
            await stream.emit(
                StreamEvent(
                    type=StreamEventType.DONE,
                    source="agent_loop.langgraph_thin",
                    metadata={"status": "failed"},
                )
            )
            await stream.close()
            return

        final_text = result.output.final_text or ""
        completed = result.termination.completed
        termination = result.termination

        # The model seam streams every round's content live (chunk-by-chunk),
        # and the final tool-less round's content IS the answer — already on
        # the wire. Do NOT re-emit ``final_text`` here or the answer would be
        # duplicated (and the persisted answer would double).  ``final_text``
        # is still carried in the RESULT payload for consumers that read it
        # from there (CLI renderer etc.).

        # ── 5. Terminal protocol (mirrors legacy/langchain adapters) ───────
        status = "completed" if completed else "failed"
        reason_value = getattr(termination, "reason", None)
        reason_name = getattr(reason_value, "value", reason_value) if reason_value else ""
        if not completed:
            detail = getattr(termination, "detail", "") or ""
            if reason_name in {"budget_exhausted", "step_limit", "tool_limit"}:
                await stream.progress(
                    f"Turn stopped: {detail or reason_name}.",
                    source="agent_loop.langgraph_thin",
                    stage=stage,
                    metadata={"trace_kind": "warning", "termination": reason_name},
                )
            elif getattr(result, "error", None) is not None:
                # C1/F2: a generic error termination carries the failure in the
                # ProviderResult's ``error`` (TurnError) — NOT on ``Termination``
                # (which has no ``error`` field). Emit a terminal ERROR event so
                # the turn's persisted ``error`` is populated and the turn-span
                # status / ``turn.failed`` counter stay aligned with the durable
                # state. Without this the stream only carried a ``result`` with
                # ``termination: error`` and the persisted error was empty.
                error_message = getattr(result.error, "message", "") or detail or reason_name
                await stream.error(
                    str(error_message),
                    source="agent_loop.langgraph_thin",
                    stage=stage,
                    metadata={"turn_terminal": True, "status": "failed"},
                )

        result_payload: dict[str, Any] = {
            "response": final_text,
            "completed": completed,
            "engine": "agent_loop.langgraph_thin",
            "provider_id": result.provider_id,
            "termination": reason_name,
            "steps": int(getattr(termination, "step_count", 0) or 0),
        }
        usage_summary = usage.summary()
        if usage_summary:
            result_payload["usage"] = usage_summary
        if mastery_mode:
            result_payload["mastery_mode"] = True
            result_payload["mastery_path_id"] = str(metadata.get("mastery_path_id", ""))

        # ── 6. Execution identity / termination report-back ────────────────
        # Generic, mode-agnostic keys the caller (mode.learn) reads to drive
        # its Teaching Session ↔ execution lifecycle.  No learner domain state
        # is written here — only the execution identity + how it ended.
        #
        # ``request.state.snapshot`` is MUTATED by the provider: for ``retry``
        # it forges a brand-new isolated identity (the supplied one is dropped),
        # and for ``start``/``resume`` it keeps the caller's.  We always report
        # the ACTUAL resolved generation so the caller records the real thread.
        actual_gen = str(request.state.snapshot.get("execution_generation") or gen)
        metadata["execution_operation"] = operation
        metadata["execution_generation"] = actual_gen
        metadata["exec_termination"] = reason_name
        metadata["exec_completed"] = completed
        result_payload["execution_generation"] = actual_gen

        await stream.result(result_payload, source="agent_loop.langgraph_thin")
        await stream.emit(
            StreamEvent(
                type=StreamEventType.DONE,
                source="agent_loop.langgraph_thin",
                metadata={"status": status},
            )
        )
        await stream.close()


# ── Plugin ────────────────────────────────────────────────────────────────────


class LangGraphThinAgentLoopPlugin(Plugin):
    """Provide ``runtime.agent_loop`` backed by P1 (LangGraph Thin).

    Dev Active Provider — switchable via profile binding:

        bindings = {"runtime.agent_loop": "agent_loop.langgraph_thin"}
    """

    manifest = PluginManifest(
        id="agent_loop.langgraph_thin",
        provides=["runtime.agent_loop"],
        requires=[
            "runtime.llm",
            "runtime.tools",
            "runtime.session",
            "runtime.prompt",
        ],
    )

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide(
            "runtime.agent_loop",
            _LangGraphThinAgentLoopAdapter(
                llm_service=ctx.require("runtime.llm"),
                tool_service=ctx.require("runtime.tools"),
            ),
        )

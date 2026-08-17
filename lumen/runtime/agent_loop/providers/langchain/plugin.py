"""LangChain / LangGraph runtime.agent_loop provider (Phase 5.5 Bake-off).

Provides ``runtime.agent_loop`` via ``create_react_agent`` + LangGraph,
adapting the existing Lumen contracts (``runtime.llm``, ``runtime.tools``,
``runtime.session``) without importing ``mode.learn`` or teaching core.

The adapter completes the ``AgentLoopService.run()`` contract — it accepts
the same ``(*, context, stream, language, **config)`` signature and
emits the same Lumen ``StreamBus`` events so the consumer (``mode.learn``
or ``chat``) is framework-agnostic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.contract import AgentLoopService, LLMService, ToolService

logger = logging.getLogger(__name__)

_PAUSE_MARKER = "__lumen_pause__"


# ── LangChain model bridge ─────────────────────────────────────────────────


class _LumenLangChainModel(BaseChatModel):
    """Wraps the Lumen ``runtime.llm`` contract as a LangChain
    ``BaseChatModel`` so ``create_react_agent`` can drive it.

    The model delegates every completion to ``llm_service.complete()``,
    keeping the Lumen contract as the single source of truth for provider
    config / credentials.  Tool calling falls back to the LLM's plain
    completion (native tool-calling parity is not guaranteed — measured in
    the bake-off report).
    """

    model_name: str = ""
    llm_service: Any = None

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> _LumenLangChainModel:
        """Return a shallow copy with the tool list attached (required by
        ``create_react_agent``)."""
        from copy import deepcopy

        new = deepcopy(self)
        new.__dict__["_bound_tools"] = list(tools)
        return new

    @property
    def _llm_type(self) -> str:
        return "lumen-langchain-bridge"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sync stub — this bridge is async-only."""
        raise NotImplementedError("Use _agenerate")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = await self.llm_service.complete(
            messages=[_msg_to_dict(m) for m in messages],
            model=self.model_name or None,
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def _msg_to_dict(msg: BaseMessage) -> dict[str, Any]:
    """Convert a LangChain message to the plain dict format Lumen's LLM
    service expects."""
    return {"role": msg.type, "content": str(msg.content or "")}


# ── Tool bridge ────────────────────────────────────────────────────────────


def _wrap_lumen_tool(
    tool_service: ToolService,
    tool_name: str,
    tool_def: Any,
    *,
    context: Any,
    stream: Any,
) -> Any:
    """Wrap a single Lumen tool as a LangChain ``StructuredTool``.

    The LangChain wrapper calls ``tool_service.execute(tool_name, **kwargs)``
    which routes through the Lumen dispatch pipeline (alias resolution,
    kwarg augmentation, ``ToolResult`` lifecycle).

    **Interrupt bridge**: when the tool result carries ``pause_for_user``
    (e.g. ``ask_user``), the wrapper emits a ``pending_user_input`` event,
    awaits the runtime's reply waiter (``context.metadata["wait_for_user_reply"]``),
    then returns the user's answer as the tool content.  This keeps the
    Lumen interrupt/resume protocol intact inside the LangGraph loop.
    """
    schema = tool_def.to_openai_schema()
    func_schema = schema.get("function", schema)
    desc = str(func_schema.get("description", "") or tool_name)
    params = func_schema.get("parameters", {})
    param_names = list((params.get("properties") or {}).keys())

    async def _execute(**kwargs: Any) -> str:
        # Drop LangChain-injected kwargs the Lumen dispatcher shouldn't see.
        filtered = {k: v for k, v in kwargs.items() if k in param_names}
        try:
            result = await tool_service.execute(tool_name, **filtered)
        except Exception as exc:
            logger.warning("LangChain tool %s failed: %s", tool_name, exc)
            return f"Error: {exc}"

        pause = getattr(result, "pause_for_user", None)
        if pause:
            return await _await_user_reply(context, stream, tool_name, pause)
        return str(getattr(result, "content", "") or "")

    # Build a StructuredTool from the Lumen ToolDefinition so tool calling
    # works through LangGraph without requiring Python docstrings.
    return StructuredTool.from_function(
        coroutine=_execute,
        name=tool_name,
        description=desc,
    )


async def _await_user_reply(
    context: Any,
    stream: Any,
    tool_name: str,
    pause_payload: Any,
) -> str:
    """Emit a pending_user_input event and block until the user replies.

    Mirrors the legacy ``ask_user`` pause/resume: the turn stays alive while
    the frontend collects the answer; the reply becomes the tool content the
    model sees next.
    """
    from lumen.runtime.stream import StreamEvent, StreamEventType

    payload = pause_payload if isinstance(pause_payload, dict) else {}
    await stream.emit(
        StreamEvent(
            type=StreamEventType.WAIT_FOR_INPUT,
            source="agent_loop.langchain",
            stage="responding",
            metadata={
                "tool_name": tool_name,
                "ask_user": payload,
                "turn_paused": True,
            },
        )
    )

    metadata = getattr(context, "metadata", {}) or {}
    waiter = metadata.get("wait_for_user_reply")
    if not callable(waiter):
        await stream.emit(
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="agent_loop.langchain",
                stage="responding",
                content="[no reply waiter]",
                metadata={"tool": tool_name},
            )
        )
        return "[no reply waiter]"

    raw_reply = await waiter()
    if raw_reply is None:
        return "[user did not reply]"
    if isinstance(raw_reply, dict):
        text = str(raw_reply.get("text") or raw_reply.get("content") or "")
    else:
        text = str(raw_reply or "")
    return text


# ── Adapter ────────────────────────────────────────────────────────────────


class _LangChainAgentLoopAdapter(AgentLoopService):
    """Agent loop runner backed by LangChain ``create_react_agent`` + LangGraph.

    Every Lumen contract dependency arrives via constructor injection (no
    global registry lookup).  The adapter never imports ``mode.learn``,
    ``learning``, or ``teaching_core``.
    """

    def __init__(
        self,
        llm_service: LLMService,
        tool_service: ToolService,
    ) -> None:
        self._llm_service = llm_service
        self._tool_service = tool_service

    async def run(
        self,
        *,
        context: Any,
        stream: Any,
        language: str = "en",
        **config: Any,
    ) -> None:
        """Execute one agentic turn using LangGraph, streaming events onto
        *stream* (a ``StreamBus``).

        Accepts the same ``**config`` kwargs as the legacy adapter so
        ``mode.learn`` passes the same pipeline dependencies.
        """
        from lumen.runtime.stream import StreamEvent, StreamEventType

        user_message = str(getattr(context, "user_message", "") or "")
        metadata = getattr(context, "metadata", {}) or {}
        enabled_tools = getattr(context, "enabled_tools", None) or []
        mastery_mode = bool(metadata.get("mastery_mode", False))
        stage = "responding"

        # ── 1. Build the LangChain model ───────────────────────────────────
        model = _build_model(self._llm_service, config)

        # ── 2. Wrap enabled tools ──────────────────────────────────────────
        definitions = self._tool_service.get_definitions(enabled_tools)
        wrapped = [
            _wrap_lumen_tool(
                self._tool_service,
                d.name,
                d,
                context=context,
                stream=stream,
            )
            for d in definitions
        ]

        # ── 3. Build system prompt ─────────────────────────────────────────
        system_prompt = _build_system_prompt(context, language, mastery_mode)
        prompt = SystemMessage(content=system_prompt)

        # ── 4. Create the agent graph ──────────────────────────────────────
        graph = create_react_agent(model, wrapped, prompt=prompt)

        # ── 5. Run with streaming ──────────────────────────────────────────
        input_messages: list[BaseMessage] = [HumanMessage(content=user_message)]
        round_count = 0
        tool_steps = 0
        final_text = ""
        completed = False

        try:
            async for event in graph.astream_events(
                {"messages": input_messages},
                version="v2",
            ):
                kind = event.get("event", "")
                name = event.get("name", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk is not None:
                        text = str(getattr(chunk, "content", "") or "")
                        if text:
                            final_text += text
                            await stream.content(
                                text,
                                source="agent_loop.langchain",
                                stage=stage,
                            )

                elif kind == "on_tool_start":
                    tool_input = event.get("data", {}).get("input", {})
                    tool_name = name or str(tool_input.get("name", "unknown"))
                    await stream.tool_call(
                        tool_name,
                        tool_input,
                        source="agent_loop.langchain",
                        stage=stage,
                    )
                    tool_steps += 1

                elif kind == "on_tool_end":
                    output = event.get("data", {}).get("output", "")
                    tool_name = name or "tool"
                    await stream.tool_result(
                        tool_name,
                        str(output)[:500],
                        source="agent_loop.langchain",
                        stage=stage,
                    )

                elif kind == "on_chain_end" and name == "LangGraph":
                    output_data = event.get("data", {}).get("output", {})
                    msg_list = (
                        output_data.get("messages", []) if isinstance(output_data, dict) else []
                    )
                    if msg_list and isinstance(msg_list[-1], AIMessage):
                        last = msg_list[-1]
                        if last.content:
                            final_text = str(last.content)
                    completed = True

                round_count += 1

        except asyncio.CancelledError:
            logger.info("LangChain agent loop cancelled (turn %s)", metadata.get("turn_id"))
            completed = False
        except Exception as exc:
            logger.error("LangChain agent loop failed: %s", exc, exc_info=True)
            if round_count == 0:
                await stream.error(
                    str(exc),
                    source="agent_loop.langchain",
                    stage=stage,
                    metadata={"turn_terminal": True, "status": "failed"},
                )
                await stream.emit(
                    StreamEvent(
                        type=StreamEventType.DONE,
                        source="agent_loop.langchain",
                        metadata={"status": "failed"},
                    )
                )
                await stream.close()
                return
            await stream.progress(
                "Agent loop error; finishing with what was gathered.",
                source="agent_loop.langchain",
                stage=stage,
                metadata={"trace_kind": "warning"},
            )

        # ── 6. Emit the capability result ──────────────────────────────────
        result_payload: dict[str, Any] = {
            "response": final_text,
            "completed": completed,
            "engine": "agent_loop.langchain",
            "rounds": round_count,
            "tool_steps": tool_steps,
        }
        if mastery_mode:
            result_payload["mastery_mode"] = True
            result_payload["mastery_path_id"] = str(metadata.get("mastery_path_id", ""))

        await stream.result(result_payload, source="agent_loop.langchain")

        # ── 7. Emit the DONE event ─────────────────────────────────────────
        await stream.emit(
            StreamEvent(
                type=StreamEventType.DONE,
                source="agent_loop.langchain",
                metadata={"status": "completed" if completed else "failed"},
            )
        )
        await stream.close()


# ── Helpers ────────────────────────────────────────────────────────────────


def _build_model(llm_service: LLMService, config: dict[str, Any]) -> BaseChatModel:
    """Build a LangChain ``BaseChatModel`` from the Lumen ``runtime.llm``
    contract.

    When a ``client_factory`` is provided (production), build a
    ``langchain_openai.ChatOpenAI`` mirroring the same provider settings so
    native tool calling works end-to-end.  Otherwise fall back to the
    ``_LumenLangChainModel`` bridge that delegates to
    ``llm_service.complete()`` (no native tool calling — measured in the
    bake-off).

    ``config["langchain_model"]`` (a pre-built ``BaseChatModel``) is a
    test seam used by the A/B harness to inject a deterministic model.
    """
    injected = config.get("langchain_model")
    if isinstance(injected, BaseChatModel):
        return injected

    client_factory = config.get("client_factory")
    if client_factory is not None:
        try:
            from langchain_openai import ChatOpenAI

            from deeptutor.services.llm import get_llm_config

            llm_cfg = get_llm_config()
            model = str(getattr(llm_cfg, "model", "") or "gpt-4o-mini")
            base_url = str(getattr(llm_cfg, "base_url", "") or "") or None
            api_key = str(getattr(llm_cfg, "api_key", "") or "") or None
            return ChatOpenAI(
                model=model,
                base_url=base_url,
                api_key=api_key,
                streaming=True,
            )
        except Exception as exc:  # pragma: no cover - env dependent
            logger.debug("ChatOpenAI build failed, using bridge: %s", exc)

    return _LumenLangChainModel(model_name="", llm_service=llm_service)


def _build_system_prompt(context: Any, language: str, mastery_mode: bool) -> str:
    """Build a minimal system prompt from the context (runtime glue only —
    never teaching logic)."""
    parts = ["You are a helpful AI tutor. Answer the user's question concisely."]
    if mastery_mode:
        parts.append(
            "You are in mastery-based learning mode. Guide the learner step by "
            "step, assess understanding, and use the available tools to track "
            "progress and provide practice."
        )
    if language.startswith("zh"):
        parts.append("Respond in Chinese.")
    return "\n".join(parts)


# ── Plugin ─────────────────────────────────────────────────────────────────


class LangChainAgentLoopPlugin(Plugin):
    """Provide ``runtime.agent_loop`` backed by LangChain / LangGraph.

    Switchable via profile binding:

        bindings = {"runtime.agent_loop": "agent_loop.langchain"}
    """

    manifest = PluginManifest(
        id="agent_loop.langchain",
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
            _LangChainAgentLoopAdapter(
                llm_service=ctx.require("runtime.llm"),
                tool_service=ctx.require("runtime.tools"),
            ),
        )

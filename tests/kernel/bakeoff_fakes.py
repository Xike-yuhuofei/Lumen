"""Deterministic fakes for the A/B bake-off (Phase 5.5).

These are NOT LangChain framework fakes — they are deterministic
stand-ins for the Lumen ``runtime.llm`` / ``runtime.tools`` contracts so
the same scenario can run against both agent loops without network.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from lumen.runtime.contract import ToolService


class ScriptedLangChainModel(BaseChatModel):
    """A BaseChatModel that replays a script of AIMessages.

    ``script`` is a list of steps; each step is either a plain ``str``
    (final answer) or a dict with ``tool_calls`` (list of
    ``{"name", "args"}``).  Steps are consumed in order; the last one
    repeats.  Lets the harness drive LangGraph deterministically.
    """

    model_name: str = "scripted-fake"

    def __init__(self, script: list[Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._script = list(script)
        self._index = 0
        self._seen_messages: list[BaseMessage] = []

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "ScriptedLangChainModel":
        from copy import deepcopy

        new = deepcopy(self)
        new._bound_tools = list(tools)
        return new

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("async only")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._seen_messages.extend(messages)
        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        if isinstance(step, str):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=step))])
        raw_tool_calls = step.get("tool_calls", [])
        tool_calls = [
            {
                "name": tc["name"],
                "args": tc.get("args", {}),
                "id": f"call-{i}",
                "type": "tool_call",
            }
            for i, tc in enumerate(raw_tool_calls)
        ]
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=step.get("content", ""),
                        tool_calls=tool_calls,
                    )
                )
            ]
        )

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        if isinstance(step, str):
            for char in step:
                yield ChatGenerationChunk(message=AIMessageChunk(content=char))
                await asyncio.sleep(0)
            return

        # Tool-call step: emit the tool_call chunks so LangGraph can route.
        raw_tool_calls = step.get("tool_calls", [])
        for i, tc in enumerate(raw_tool_calls):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": _json_dumps(tc.get("args", {})),
                            "id": f"call-{i}",
                            "index": i,
                        }
                    ],
                )
            )
            await asyncio.sleep(0)
        text = step.get("content", "")
        for char in text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=char))
            await asyncio.sleep(0)


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value)


# ── Legacy-side scripted OpenAI-compatible client ──────────────────────────
#
# The legacy agent loop drives an OpenAI-compatible chat client directly
# (``client.chat.completions.create(..., stream=True)``).  To run the SAME
# scenario against the REAL legacy ``AgenticChatPipeline`` we script that
# client deterministically: each LLM call inspects the conversation and
# returns a chunk stream that either (a) requests a tool call, or (b)
# emits a plain final answer.


class _Chunk:
    def __init__(self, delta: Any, finish_reason: str | None = None, usage: Any = None) -> None:
        self.choices = [type("_Ch", (), {"delta": delta, "finish_reason": finish_reason})()]
        self.usage = usage


class _Delta:
    def __init__(self, content: str | None = None, tool_calls: list[Any] | None = None) -> None:
        self.content = content
        self.reasoning_content = None
        self.reasoning = None
        self.tool_calls = tool_calls


def _tool_call_delta(name: str, args: dict[str, Any], call_id: str = "call-1") -> Any:
    function = type("_F", (), {"name": name, "arguments": _json_dumps(args)})()
    return type("_TC", (), {"index": 0, "id": call_id, "function": function})()


class ScriptedOpenAIClient:
    """An OpenAI-compatible client that replays a script of turns.

    ``script`` is a list of steps; each step is either:

    * ``{"tool_calls": [{"name", "args"}]}`` — the model asks for tool
      calls (the loop will dispatch them and call the client again); or
    * ``"final answer text"`` — the model answers and the loop finishes.

    Step selection is conversation-aware: tool-call steps are consumed on
    the first turn; a final-answer step is used once the conversation
    already contains ``role=tool`` messages (i.e. after dispatch).
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    @property
    def chat(self) -> "ScriptedChat":
        return ScriptedChat(self)

    def _select_step(self, messages: list[dict[str, Any]]) -> Any:
        has_tool_msg = any(str(m.get("role")) == "tool" for m in messages)
        # Find first unconsumed tool-call step; otherwise the final text.
        for step in self._script:
            if isinstance(step, dict) and step.get("tool_calls"):
                if not has_tool_msg:
                    return step
        # After tools ran, emit the last plain-text step.
        for step in reversed(self._script):
            if isinstance(step, str):
                return step
        return "Answer."


class ScriptedChat:
    def __init__(self, client: ScriptedOpenAIClient) -> None:
        self.completions = ScriptedCompletions(client)


class ScriptedCompletions:
    def __init__(self, client: ScriptedOpenAIClient) -> None:
        self._client = client

    async def create(self, **kwargs: Any) -> AsyncIterator[Any]:
        messages = kwargs.get("messages") or []
        self._client.calls.append({"kwargs": kwargs})
        step = self._client._select_step(messages)
        if isinstance(step, dict):
            tool_calls = step.get("tool_calls", [])
            return _tool_call_stream(tool_calls)
        return _text_stream(str(step))


async def _tool_call_stream(tool_calls: list[dict[str, Any]]) -> AsyncIterator[Any]:
    yield _Chunk(
        delta=_Delta(
            tool_calls=[_tool_call_delta(tc["name"], tc.get("args", {})) for tc in tool_calls]
        )
    )


async def _text_stream(text: str) -> AsyncIterator[Any]:
    for char in text:
        yield _Chunk(delta=_Delta(content=char), finish_reason=None)
        await asyncio.sleep(0)
    yield _Chunk(delta=_Delta(), finish_reason="stop")


class FakeBakeoffToolService(ToolService):
    """Deterministic tool registry for bake-off scenarios."""

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._tools: dict[str, Any] = dict(tools or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool: Any) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Any | None:
        return self._tools.get(name)

    def get_enabled(self, names: list[str]) -> list[Any]:
        return [self._tools[n] for n in names if n in self._tools]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def deferred_tools(self) -> list[Any]:
        return []

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return await tool.execute(**kwargs)

    def get_definitions(self, names: list[str] | None = None) -> list[Any]:
        tools = self._tools.values() if names is None else self.get_enabled(names)
        return [t.get_definition() for t in tools]

    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [d.to_openai_schema() for d in self.get_definitions(names)]

    def get_prompt_hints(self, names: list[str], language: str = "en") -> list[Any]:
        return [(n, self._tools[n].get_prompt_hints(language=language)) for n in names]

    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",
        **opts: Any,
    ) -> str:
        return ", ".join(names)


def make_calc_tool() -> Any:
    """A deterministic calculator tool with a Lumen ToolDefinition."""

    from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

    class CalcTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="calc",
                description="Add two integers.",
                parameters=[
                    ToolParameter(name="a", type="integer", description="First operand"),
                    ToolParameter(name="b", type="integer", description="Second operand"),
                ],
            )

        async def execute(self, **kwargs: Any) -> ToolResult:
            a = int(kwargs.get("a", 0))
            b = int(kwargs.get("b", 0))
            return ToolResult(content=f"{a} + {b} = {a + b}")

    return CalcTool()


def make_ask_tool() -> Any:
    """A deterministic ask_user tool with a Lumen ToolDefinition."""

    from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

    class AskTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="ask_user",
                description="Ask the user a question and await their answer.",
                parameters=[
                    ToolParameter(name="question", type="string", description="Question to ask"),
                ],
            )

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(
                content="[awaiting user reply]",
                metadata={"ask_user": {"questions": [{"prompt": kwargs.get("question", "")}]}},
                pause_for_user={"questions": [{"prompt": kwargs.get("question", "")}]},
            )

    return AskTool()

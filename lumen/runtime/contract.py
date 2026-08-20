"""Runtime service contracts for the Plugin Kernel (Phase 2).

Each contract is a minimal abstract interface describing what a consumer
genuinely needs from the runtime layer.  Adapter plugins implement these
by wrapping the existing ``lumen`` implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

__all__ = [
    "AgentLoopService",
    "AgentService",
    "LLMService",
    "PromptService",
    "SessionService",
    "ToolService",
]

# ── runtime.session ──────────────────────────────────────────────────────


class SessionService(ABC):
    """Session store and turn runtime that a capability needs to manage
    conversations, persist turns, and stream events to subscribers."""

    @abstractmethod
    async def ensure_session(self, session_id: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def get_turn(self, turn_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def start_turn(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    @abstractmethod
    async def cancel_turn(self, turn_id: str) -> bool: ...

    @abstractmethod
    async def subscribe_turn(
        self, turn_id: str, after_seq: int = 0
    ) -> AsyncIterator[dict[str, Any]]: ...

    @abstractmethod
    async def get_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        **kwargs: Any,
    ) -> int | str: ...

    @abstractmethod
    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool: ...


# ── runtime.prompt ────────────────────────────────────────────────────────


class PromptService(ABC):
    """Prompt loading for any module/agent/language combination."""

    @abstractmethod
    def load_prompt(
        self,
        module: str,
        agent: str,
        language: str = "en",
        subdirectory: str | None = None,
    ) -> dict[str, Any]: ...


# ── runtime.tools ─────────────────────────────────────────────────────────


class ToolService(ABC):
    """Tool registry — register, look up, execute, and build schemas for tools."""

    @abstractmethod
    def register(self, tool: Any) -> None: ...

    @abstractmethod
    def get(self, name: str) -> Any | None: ...

    @abstractmethod
    def get_enabled(self, names: list[str]) -> list[Any]: ...

    @abstractmethod
    def list_tools(self) -> list[str]: ...

    @abstractmethod
    def deferred_tools(self) -> list[Any]: ...

    @abstractmethod
    async def execute(self, name: str, /, **kwargs: Any) -> Any: ...

    @abstractmethod
    def get_definitions(self, names: list[str] | None = None) -> list[Any]: ...

    @abstractmethod
    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_prompt_hints(self, names: list[str], language: str = "en") -> list[tuple[str, Any]]: ...

    @abstractmethod
    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",
        **opts: Any,
    ) -> str: ...


# ── runtime.llm ────────────────────────────────────────────────────────────


class LLMService(ABC):
    """LLM client — build an OpenAI-compatible client handle and make
    completion calls."""

    @abstractmethod
    def build_openai_client(self, config: Any) -> Any:
        """Return an OpenAI-compatible client handle for *config*."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> str: ...


# ── runtime.agent ──────────────────────────────────────────────────────────


class AgentService(ABC):
    """Agent pipeline factory — construct a pipeline that can run a chat
    turn with the given language and config."""

    @abstractmethod
    async def create_pipeline(self, language: str = "en", **config: Any) -> Any: ...


# ── runtime.agent_loop ──────────────────────────────────────────────────────


class AgentLoopService(ABC):
    """Agent loop runner — execute one agentic turn, emitting events through
    the stream bus.  This is the top-level consumer of all other runtime
    services."""

    @abstractmethod
    async def run(
        self,
        pipeline: Any,
        context: Any,
        stream: Any,
    ) -> None: ...

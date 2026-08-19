"""Runtime adapters — bridge existing ``lumen.runtime.*`` implementations onto
the frozen Provider Contract v1 (``lumen.evolution.contract``).

These adapters let an existing ToolService / LLM / Session surface be consumed
through the contract *without* importing mode.learn, without mutating runtime
internals, and without coupling the upper layer to a specific provider.
"""

from __future__ import annotations

from typing import Any

from lumen.evolution.contract import (
    Model,
    ToolRuntime,
)


class ContractToolRuntime(ToolRuntime):
    """Wrap an existing ``runtime.tools`` ToolService as a ``ToolRuntime``.

    The existing registry stays the single Source of Truth for tool lifetime;
    this adapter is read-only over it (no register/unregister surface).
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_available(self) -> list[str]:
        try:
            return list(self._service.list_tools())
        except Exception:
            return []

    def definition(self, name: str) -> Any:
        try:
            return self._service.get(name)
        except Exception:
            return None

    def build_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        try:
            return self._service.build_openai_schemas(names)
        except Exception:
            return []

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        return await self._service.execute(name, **kwargs)


class CallableModel(Model):
    """Adapter over any ``async def(messages, **kwargs) -> Any`` model seam.

    Used to drive the contract off the existing ``LLMService`` or a plain
    callable, and by the harness to inject deterministic scripts.
    """

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[Any] | None = None,
        seed: int | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self._fn(messages, tools=tools, seed=seed, **kwargs)


__all__ = ["ContractToolRuntime", "CallableModel"]
"""Runtime adapter plugin — bridge existing ``lumen`` tool registry
into the Plugin Kernel via :class:`ToolService`."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.tools.contract import ToolService


class _ToolServiceAdapter(ToolService):
    """Wraps ``lumen.runtime.tools.registry.ToolRegistry``."""

    def __init__(self) -> None:
        self._registry: Any = None

    def _ensure_loaded(self) -> None:
        if self._registry is not None:
            return
        from lumen.runtime.tools.registry import get_tool_registry

        self._registry = get_tool_registry()

    def register(self, tool: Any) -> None:
        self._ensure_loaded()
        self._registry.register(tool)

    def get(self, name: str) -> Any | None:
        self._ensure_loaded()
        return self._registry.get(name)

    def get_enabled(self, names: list[str]) -> list[Any]:
        self._ensure_loaded()
        return self._registry.get_enabled(names)

    def list_tools(self) -> list[str]:
        self._ensure_loaded()
        return self._registry.list_tools()

    def deferred_tools(self) -> list[Any]:
        self._ensure_loaded()
        return self._registry.deferred_tools()

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        self._ensure_loaded()
        return await self._registry.execute(name, **kwargs)

    def get_definitions(self, names: list[str] | None = None) -> list[Any]:
        self._ensure_loaded()
        return self._registry.get_definitions(names)

    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return self._registry.build_openai_schemas(names)

    def get_prompt_hints(self, names: list[str], language: str = "en") -> list[tuple[str, Any]]:
        self._ensure_loaded()
        return self._registry.get_prompt_hints(names, language=language)

    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",
        **opts: Any,
    ) -> str:
        self._ensure_loaded()
        return self._registry.build_prompt_text(names, format=format, language=language, **opts)


class ToolPlugin(Plugin):
    """Provide the tool registry as ``runtime.tools``."""

    manifest = PluginManifest(id="runtime.tools", provides=["runtime.tools"])

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("runtime.tools", _ToolServiceAdapter())

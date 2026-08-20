"""Runtime adapter plugin — bridge existing ``lumen`` prompt manager
into the Plugin Kernel via :class:`PromptService`."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.prompt.contract import PromptService


class _PromptServiceAdapter(PromptService):
    """Wraps ``lumen.services.prompt.manager.PromptManager``."""

    def __init__(self) -> None:
        self._manager: Any = None

    def _ensure_loaded(self) -> None:
        if self._manager is not None:
            return
        from .manager import get_prompt_manager

        self._manager = get_prompt_manager()

    def load_prompt(
        self,
        module: str,
        agent: str,
        language: str = "en",
        subdirectory: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_loaded()
        return self._manager.load_prompts(module, agent, language, subdirectory=subdirectory)


class PromptPlugin(Plugin):
    """Provide the prompt manager as ``runtime.prompt``."""

    manifest = PluginManifest(id="runtime.prompt", provides=["runtime.prompt"])

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("runtime.prompt", _PromptServiceAdapter())

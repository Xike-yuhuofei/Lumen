"""Knowledge source discovery adapter plugin."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.knowledge.sources.contract import KnowledgeSourceService


class _KnowledgeSourceServiceAdapter(KnowledgeSourceService):
    """Wraps ``lumen.shared.knowledge.manager.KnowledgeBaseManager``."""

    def __init__(self, kb_manager: Any) -> None:
        self._kb_manager = kb_manager

    def list_knowledge_bases(self) -> list[str]:
        return self._kb_manager.list_knowledge_bases()

    def get_info(self, name: str | None = None) -> dict[str, Any]:
        return self._kb_manager.get_info(name)

    def get_kb_path(self, name: str | None = None) -> str:
        return str(self._kb_manager.get_knowledge_base_path(name))


class KnowledgeSourcesPlugin(Plugin):
    """Provide knowledge base source discovery as ``knowledge.sources``."""

    manifest = PluginManifest(id="knowledge.sources", provides=["knowledge.sources"])

    async def setup(self, ctx: PluginContext) -> None:
        from lumen.shared.knowledge.manager import KnowledgeBaseManager
        from lumen.shared._util.path_service import get_path_service

        kb_root = get_path_service().get_knowledge_bases_root()
        manager = KnowledgeBaseManager(base_dir=str(kb_root))
        ctx.provide("knowledge.sources", _KnowledgeSourceServiceAdapter(manager))

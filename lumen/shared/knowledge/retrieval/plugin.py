"""Knowledge retrieval (RAG) adapter plugin."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.contract import KnowledgeRetrievalService, RetrievalResult


class _KnowledgeRetrievalServiceAdapter(KnowledgeRetrievalService):
    """Wraps ``lumen.shared.knowledge.rag.service.RAGService`` (thin conversion
    from the service's dict result to the contract envelope)."""

    def __init__(self, rag_service: Any) -> None:
        self._rag = rag_service

    async def search(
        self,
        query: str,
        kb_name: str,
        **kwargs: Any,
    ) -> RetrievalResult:
        raw = await self._rag.search(query=query, kb_name=kb_name, **kwargs)
        content = str(raw.get("content") or raw.get("answer") or "")
        sources = raw.get("sources") or []
        return RetrievalResult(content=content, sources=sources, **raw)

    async def initialize(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        return await self._rag.initialize(kb_name=kb_name, file_paths=file_paths, **kwargs)

    async def add_documents(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        return await self._rag.add_documents(kb_name=kb_name, file_paths=file_paths, **kwargs)


class KnowledgeRetrievalPlugin(Plugin):
    """Provide RAG retrieval as ``knowledge.retrieval``.

    Depends on ``knowledge.sources``: retrieval targets a knowledge base that
    source discovery manages.
    """

    manifest = PluginManifest(
        id="knowledge.retrieval",
        provides=["knowledge.retrieval"],
        requires=["knowledge.sources"],
    )

    async def setup(self, ctx: PluginContext) -> None:
        from lumen.shared.knowledge.rag.service import RAGService

        ctx.provide("knowledge.retrieval", _KnowledgeRetrievalServiceAdapter(RAGService()))

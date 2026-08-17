"""Knowledge parsing adapter plugin."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.contract import KnowledgeParsingService, ParsedDocument


class _KnowledgeParsingServiceAdapter(KnowledgeParsingService):
    """Wraps ``deeptutor.services.parsing.service.ParseService``."""

    def __init__(self, parse_service: Any) -> None:
        self._parse = parse_service

    def parse(
        self,
        source_path: str,
        *,
        engine: str | None = None,
    ) -> ParsedDocument:
        doc = self._parse.parse(source_path, engine=engine)
        return ParsedDocument(
            markdown=getattr(doc, "markdown", ""), blocks=getattr(doc, "blocks", [])
        )


class KnowledgeParsingPlugin(Plugin):
    """Provide document parsing as ``knowledge.parsing``."""

    manifest = PluginManifest(id="knowledge.parsing", provides=["knowledge.parsing"])

    async def setup(self, ctx: PluginContext) -> None:
        from deeptutor.services.parsing.service import ParseService

        ctx.provide("knowledge.parsing", _KnowledgeParsingServiceAdapter(ParseService()))

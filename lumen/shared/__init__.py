"""Shared services subpackage — contracts and adapter plugins for the
plugin kernel (knowledge / memory / notebook / rendering)."""
from lumen.shared.knowledge.parsing import (
    KnowledgeParsingPlugin,
    KnowledgeParsingService,
    ParsedDocument,
)
from lumen.shared.knowledge.retrieval import (
    KnowledgeRetrievalPlugin,
    KnowledgeRetrievalService,
    RetrievalResult,
)
from lumen.shared.knowledge.sources import KnowledgeSourceService, KnowledgeSourcesPlugin
from lumen.shared.memory import MemoryPlugin, MemoryService
from lumen.shared.notebook import NotebookPlugin, NotebookService
from lumen.shared.rendering import RenderingPlugin, RenderingService

__all__ = [
    "KnowledgeParsingPlugin", "KnowledgeParsingService",
    "KnowledgeRetrievalPlugin", "KnowledgeRetrievalService",
    "KnowledgeSourcesPlugin", "KnowledgeSourceService",
    "MemoryPlugin", "MemoryService",
    "NotebookPlugin", "NotebookService",
    "ParsedDocument",
    "RenderingPlugin", "RenderingService",
    "RetrievalResult",
]

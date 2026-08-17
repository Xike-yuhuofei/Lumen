"""Shared service contracts for the Plugin Kernel (Phase 3).

Each contract is a minimal abstract interface describing what a consumer
genuinely needs from the shared knowledge / memory / notebook / rendering
layers.  Adapter plugins implement these by wrapping the existing
``deeptutor`` implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# ── knowledge.sources ─────────────────────────────────────────────────────


class KnowledgeSourceService(ABC):
    """Knowledge base source discovery — list, describe, and locate KBs."""

    @abstractmethod
    def list_knowledge_bases(self) -> list[str]: ...

    @abstractmethod
    def get_info(self, name: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def get_kb_path(self, name: str | None = None) -> str: ...


# ── knowledge.retrieval ────────────────────────────────────────────────────


class RetrievalResult:
    """Minimal retrieved chunk + answer envelope."""

    def __init__(self, content: str, sources: list[dict] | None = None, **kwargs: Any) -> None:
        self.content = content
        self.sources = sources or []
        self.extra = kwargs


class KnowledgeRetrievalService(ABC):
    """RAG retrieval — search an indexed knowledge base and return content."""

    @abstractmethod
    async def search(
        self,
        query: str,
        kb_name: str,
        **kwargs: Any,
    ) -> RetrievalResult: ...

    @abstractmethod
    async def initialize(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool: ...

    @abstractmethod
    async def add_documents(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool: ...


# ── knowledge.parsing ──────────────────────────────────────────────────────


class ParsedDocument:
    """Result of parsing a document file."""

    def __init__(
        self,
        markdown: str,
        blocks: list[dict] | None = None,
        **kwargs: Any,
    ) -> None:
        self.markdown = markdown
        self.blocks = blocks or []


class KnowledgeParsingService(ABC):
    """Document parsing — convert a file path to structured Markdown."""

    @abstractmethod
    def parse(
        self,
        source_path: str,
        *,
        engine: str | None = None,
    ) -> ParsedDocument: ...


# ── memory ──────────────────────────────────────────────────────────────────


class MemoryService(ABC):
    """Persistent memory store — read, write, and list memory layers."""

    @abstractmethod
    async def read(self, layer: str, key: str) -> dict[str, Any] | None:
        """Read a memory document (returns raw dict)."""
        ...

    @abstractmethod
    async def read_concat(self) -> str:
        """Concatenate all L3 slots for the ``read_memory`` tool."""
        ...

    @abstractmethod
    async def overwrite(self, layer: str, key: str, content: str) -> None: ...

    @abstractmethod
    async def delete_entry(self, layer: str, key: str, entry_id: str) -> bool: ...

    @abstractmethod
    def overview(self) -> list[dict[str, Any]]: ...


# ── notebook ────────────────────────────────────────────────────────────────


class NotebookService(ABC):
    """Notebook CRUD — manage notebooks and their records."""

    @abstractmethod
    def create(
        self, name: str, description: str = "", color: str = "#3B82F6", icon: str = "book"
    ) -> dict[str, Any]: ...

    @abstractmethod
    def list(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get(self, notebook_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def add_record(
        self,
        notebook_ids: list[str],
        record_type: str,
        title: str,
        user_query: str,
        output: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        kb_name: str | None = None,
    ) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_records(
        self, notebook_id: str, record_ids: list[str] | None = None
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def remove_record(self, notebook_id: str, record_id: str) -> bool: ...


# ── rendering ────────────────────────────────────────────────────────────────


class RenderingService(ABC):
    """Lightweight text rendering — Markdown cleanup, tag stripping, and
    plain-text extraction for LLM-facing output."""

    @abstractmethod
    def strip_markdown(self, text: str) -> str:
        """Strip Markdown syntax, returning plain text."""
        ...

    @abstractmethod
    def clean_thinking_tags(self, text: str) -> str:
        """Remove private model scratchpad tags (e.g. ``think`` / ``/think``)."""
        ...


__all__ = [
    "KnowledgeSourceService",
    "RetrievalResult",
    "KnowledgeRetrievalService",
    "ParsedDocument",
    "KnowledgeParsingService",
    "MemoryService",
    "NotebookService",
    "RenderingService",
]

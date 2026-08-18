"""Private shared util — RAG service access for runtime code.

Runtime tool implementations reach the RAG service through this private
channel (per the plugin dependency gates, which allow runtime code to import
only ``lumen.shared._util.*``).
"""

from __future__ import annotations

from lumen.shared.knowledge.rag.service import RAGService

__all__ = ["RAGService"]

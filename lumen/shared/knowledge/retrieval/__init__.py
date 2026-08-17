"""Knowledge retrieval (RAG) — search and index KBs."""
from lumen.shared.knowledge.retrieval.contract import KnowledgeRetrievalService, RetrievalResult
from lumen.shared.knowledge.retrieval.plugin import KnowledgeRetrievalPlugin

__all__ = ["KnowledgeRetrievalService", "KnowledgeRetrievalPlugin", "RetrievalResult"]

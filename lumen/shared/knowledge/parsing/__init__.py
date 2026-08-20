"""Knowledge parsing — document-to-Markdown conversion.

Public entry points:

* canonical engine-pluggable parse layer — :class:`ParseService`,
  :func:`get_parse_service`, :class:`Parser`, :class:`ReadinessReport`,
  :class:`ParserSignature`, :class:`ParserError`, :class:`ParsedDocument`
* plugin-kernel contract + adapter — :class:`KnowledgeParsingService`,
  :class:`KnowledgeParsingPlugin`, :class:`ParsedDocument`

``ParseService`` / ``get_parse_service`` are imported lazily so this package
stays importable without pulling the lumen config chain (which itself
depends on the shared package) — no import cycle at package load.
"""

from __future__ import annotations

from lumen.shared.knowledge.parsing.base import Parser, ReadinessReport
from lumen.shared.knowledge.parsing.contract import KnowledgeParsingService, ParsedDocument
from lumen.shared.knowledge.parsing.plugin import KnowledgeParsingPlugin
from lumen.shared.knowledge.parsing.signature import ParserSignature
from lumen.shared.knowledge.parsing.types import ParserError


def get_parse_service():
    """Return the process-wide :class:`ParseService` singleton."""
    from lumen.shared.knowledge.parsing.service import get_parse_service as _get

    return _get()


__all__ = [
    "KnowledgeParsingService",
    "KnowledgeParsingPlugin",
    "ParseService",
    "Parser",
    "ParserError",
    "ParserSignature",
    "ParsedDocument",
    "ReadinessReport",
    "get_parse_service",
]

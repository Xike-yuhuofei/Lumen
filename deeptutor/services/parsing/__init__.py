"""Deprecated compatibility facade — see ``lumen.shared.knowledge.parsing``.

``ParseService`` / ``get_parse_service`` stay imported lazily so this package
remains importable before the service module lands and to avoid pulling engine
deps (and the config → parsing cycle) at import time.
"""

from __future__ import annotations

from lumen.shared.knowledge.parsing.base import Parser, ReadinessReport
from lumen.shared.knowledge.parsing.signature import ParserSignature
from lumen.shared.knowledge.parsing.types import ParsedDocument, ParserError


def get_parse_service():
    """Return the process-wide :class:`ParseService` singleton."""
    from lumen.shared.knowledge.parsing.service import get_parse_service as _get

    return _get()


__all__ = [
    "ParsedDocument",
    "ParserError",
    "Parser",
    "ReadinessReport",
    "ParserSignature",
    "get_parse_service",
]

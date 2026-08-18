"""Deprecated compatibility facade — see ``lumen.shared.knowledge.parsing.types``."""

from lumen.shared.knowledge.parsing.types import *  # noqa: F401,F403
from lumen.shared.knowledge.parsing.types import ParsedDocument, ParserError

__all__ = ["ParsedDocument", "ParserError"]

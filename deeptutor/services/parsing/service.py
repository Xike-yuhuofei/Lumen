"""Deprecated compatibility facade — see ``lumen.shared.knowledge.parsing.service``."""

from lumen.shared.knowledge.parsing.engines.factory import get_parser
from lumen.shared.knowledge.parsing.service import *  # noqa: F401,F403
from lumen.shared.knowledge.parsing.service import ParseService, get_parse_service

__all__ = ["ParseService", "get_parse_service", "get_parser"]
"""Deprecated compatibility facade — see ``lumen.shared.knowledge.parsing.base``."""

from lumen.shared.knowledge.parsing.base import *  # noqa: F401,F403
from lumen.shared.knowledge.parsing.base import Parser, ReadinessReport

__all__ = ["Parser", "ReadinessReport"]

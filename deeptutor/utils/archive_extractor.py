"""Deprecated compatibility facade — see ``lumen.shared._util.archive_extractor``.

The safe ZIP extractor is owned by ``lumen/shared/_util``.  This module
re-exports it for existing importers and tests only.
"""
from __future__ import annotations

from lumen.shared._util.archive_extractor import *  # noqa: F401,F403
from lumen.shared._util.archive_extractor import __all__  # noqa: F401

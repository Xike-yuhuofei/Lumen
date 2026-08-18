"""Deprecated compatibility facade — see ``lumen.shared._util.auth``.

The authentication service is owned by ``lumen/shared/_util``.  This module
re-exports it for existing importers and tests only.
"""
from __future__ import annotations

from lumen.shared._util.auth import *  # noqa: F401,F403
from lumen.shared._util.auth import __all__  # noqa: F401

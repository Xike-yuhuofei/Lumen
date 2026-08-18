# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared._util.errors``.

The base exception classes are owned by ``lumen/shared/_util``.  This module
re-exports them for existing importers and tests only.
"""

from __future__ import annotations

from lumen.shared._util.errors import *  # noqa: F401,F403
from lumen.shared._util.errors import __all__  # noqa: F401

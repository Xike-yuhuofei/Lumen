# ruff: noqa: F401,F403
"""Deprecated compatibility facade — see ``lumen.shared._util.storage``.

The attachment store is owned by ``lumen/shared/_util/storage`` (canonical).
This package re-exports it for existing importers and tests only.
"""

from __future__ import annotations

from lumen.shared._util.storage import *  # noqa: F401,F403
from lumen.shared._util.storage import __all__  # noqa: F401

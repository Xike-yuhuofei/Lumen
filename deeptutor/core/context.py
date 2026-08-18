# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.context``.

The unified turn context (``UnifiedContext`` / ``Attachment``) is owned by
``lumen/runtime``.  This module re-exports them for existing importers and
tests only.
"""

from __future__ import annotations

from lumen.runtime.context import *  # noqa: F401,F403

__all__ = ["Attachment", "UnifiedContext"]

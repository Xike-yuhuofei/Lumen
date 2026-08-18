"""Deprecated compatibility facade — see ``lumen.runtime.i18n``.

Runtime i18n helpers are owned by ``lumen/runtime/i18n``.  This module
re-exports them for existing importers and tests only.
"""
from __future__ import annotations

from lumen.runtime.i18n import (  # noqa: F401
    StatusI18n,
    capability_description_i18n,
    localized_description,
    tool_description_i18n,
)

__all__ = [
    "StatusI18n",
    "capability_description_i18n",
    "localized_description",
    "tool_description_i18n",
]

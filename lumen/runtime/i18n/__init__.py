"""Runtime i18n helpers.

Two complementary pieces live here (migrated from ``lumen/i18n``):

* :mod:`~lumen.runtime.i18n.metadata_i18n` — static localized display copy
  for built-in capabilities and tools (used by the settings UI / API).
* :mod:`~lumen.runtime.i18n.status_i18n` — per-feature localized status-string
  lookup wired into the :class:`~lumen.runtime.prompt.manager.PromptManager`,
  used by capability pipelines to stream locale-aware progress messages.

``lumen.i18n`` re-exports these for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.i18n.metadata_i18n import (
    capability_description_i18n,
    localized_description,
    tool_description_i18n,
)
from lumen.runtime.i18n.status_i18n import StatusI18n

__all__ = [
    "StatusI18n",
    "capability_description_i18n",
    "localized_description",
    "tool_description_i18n",
]

"""Private shared util — knowledge-base manifest access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the KB manifest constants and
renderers through that private channel.
"""

from __future__ import annotations

from lumen.shared.knowledge.manifest import (
    KB_FILES_DEFAULT_LIMIT,
    KB_FILES_MAX_LIMIT,
    render_manifest_note,
    render_manifest_report,
)

__all__ = [
    "KB_FILES_DEFAULT_LIMIT",
    "KB_FILES_MAX_LIMIT",
    "render_manifest_note",
    "render_manifest_report",
]

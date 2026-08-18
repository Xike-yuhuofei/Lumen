"""Private shared util — interface-settings access for runtime code.

See ``lumen.shared._util.memory`` for the rationale.
"""

from __future__ import annotations

from lumen.shared.settings.interface_settings import (
    get_response_language,
    get_ui_language,
    resolve_languages,
)

__all__ = ["get_response_language", "get_ui_language", "resolve_languages"]

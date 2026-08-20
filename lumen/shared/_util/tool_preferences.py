"""Tool-preference / UI-settings persistence shared by the API and runtime.

Canonical home for the user's toggleable-tool list, the interface settings
file, and the "enabled optional tools" resolution the chat pipeline uses when a
turn doesn't carry an explicit ``tools`` list.  Migrated from
``lumen/api/routers/settings`` and ``lumen/tools/builtin``.
"""

from __future__ import annotations

import json
from typing import Any

from lumen.shared._util.path_service import get_path_service
from lumen.shared._util.user import allowed_optional_tools
from lumen.shared.settings.interface_settings import (
    DEFAULT_UI_SETTINGS as INTERFACE_DEFAULTS,
)
from lumen.shared.settings.interface_settings import resolve_languages

# Experience Enhancement). Everything else in BUILTIN_TOOL_NAMES is mounted
# automatically by the chat pipeline under per-tool context gates and is
# locked-on from the user's perspective. Ordering here is the canonical
# display order for the settings page.
USER_TOGGLEABLE_TOOL_NAMES: tuple[str, ...] = (
    "brainstorm",
    "web_search",
    "reason",
)

DEFAULT_SIDEBAR_NAV_ORDER = {
    "start": ["/", "/history", "/knowledge", "/notebook"],
    "learnResearch": ["/question", "/solver", "/research"],
}

DEFAULT_UI_SETTINGS = {
    # theme / language / response_language come from the module that owns
    # interface.json, so the two readers of that file can't drift on what a
    # fresh install defaults to.
    **INTERFACE_DEFAULTS,
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": DEFAULT_SIDEBAR_NAV_ORDER,
    # User-toggleable chat tools. Default = all on; the /settings/tools page
    # is the single switchboard. Removed names (e.g. tools that ship later
    # and the user hasn't seen yet) are ignored on read; missing names from a
    # legacy file fall back to the default (all on).
    "enabled_optional_tools": list(USER_TOGGLEABLE_TOOL_NAMES),
    # When true, chat auto-plays each assistant reply via TTS. Per-user UI
    # preference (not catalog); the chat surface also keeps a per-session
    # override on top of this global default.
    "voice_autoplay": False,
    # Seconds the chat UI waits for any turn event before declaring the
    # connection timed out. Bumped from 60 → 180 so slow tools (image/video
    # generation) don't trip it; user-adjustable in Settings > Network.
    "chat_response_timeout": 180,
}


def settings_file() -> Any:
    return get_path_service().get_settings_file("interface")


def load_ui_settings() -> dict[str, Any]:
    file = settings_file()
    if file.exists():
        try:
            with open(file, encoding="utf-8") as handle:
                saved = json.load(handle)
                # resolve_languages owns the legacy migration (a file predating
                # the UI/response split inherits its one language into both).
                merged = {**DEFAULT_UI_SETTINGS, **saved, **resolve_languages(saved)}
                # Filter persisted enabled_optional_tools to current
                # toggleable set so retired tool names can't leak into
                # the per-turn payload.
                merged["enabled_optional_tools"] = sanitize_enabled_tools(
                    merged.get("enabled_optional_tools")
                )
                return merged
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def sanitize_enabled_tools(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(USER_TOGGLEABLE_TOOL_NAMES)
    allowed = set(USER_TOGGLEABLE_TOOL_NAMES)
    seen: set[str] = set()
    out: list[str] = []
    for name in value:
        if isinstance(name, str) and name in allowed and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def get_enabled_optional_tools() -> list[str]:
    """Return the user's currently-enabled toggleable tool names.

    Source of truth for the chat pipeline when a turn doesn't ship an
    explicit ``tools`` list. Intersected with the admin grant whitelist so
    a restricted user's saved toggles can't resurrect a revoked tool.
    """
    enabled = sanitize_enabled_tools(load_ui_settings().get("enabled_optional_tools"))
    allowed = allowed_optional_tools()
    if allowed is not None:
        enabled = [name for name in enabled if name in allowed]
    return enabled


def save_ui_settings(settings: dict[str, Any]) -> None:
    file = settings_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)


__all__ = [
    "DEFAULT_UI_SETTINGS",
    "USER_TOGGLEABLE_TOOL_NAMES",
    "get_enabled_optional_tools",
    "sanitize_enabled_tools",
    "load_ui_settings",
    "save_ui_settings",
    "settings_file",
]

# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.prompt``.

The prompt manager is owned by ``lumen/runtime/prompt``.  This package
re-exports it for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.prompt.manager import PromptManager, get_prompt_manager
from lumen.shared._util.language import (
    append_language_directive,
    language_directive,
    language_label,
    normalize_language,
)

__all__ = [
    "PromptManager",
    "append_language_directive",
    "get_prompt_manager",
    "language_directive",
    "language_label",
    "normalize_language",
]

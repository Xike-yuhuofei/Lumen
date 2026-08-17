"""Shared language directives for prompt-driven LLM calls.

Compatibility facade — the real implementation now lives in
``lumen.shared._util.language``. Retained only so existing importers keep the
historical path; new code must import from ``lumen.shared._util.language``.
"""

from __future__ import annotations

from lumen.shared._util.language import (  # noqa: F401
    append_language_directive,
    language_directive,
    language_label,
    normalize_language,
)

__all__ = [
    "append_language_directive",
    "language_directive",
    "language_label",
    "normalize_language",
]
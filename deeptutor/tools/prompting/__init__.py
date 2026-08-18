"""Deprecated compatibility facade — see ``lumen.runtime.tools.prompting``.

Tool prompt-hint loading / rendering is owned by ``lumen/runtime/tools``.
This module re-exports it for existing importers and tests only.  The
``hints`` data directory lives in ``lumen/runtime/tools/prompting/hints``.
"""

from __future__ import annotations

from lumen.runtime.tools.prompting import (  # noqa: F401
    ToolPromptComposer,
    compose_prompt_text,
    load_prompt_hints,
)

__all__ = ["ToolPromptComposer", "compose_prompt_text", "load_prompt_hints"]

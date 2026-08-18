"""Private shared util — model-selection runtime helpers for runtime code.

See ``lumen.shared._util.memory`` for the rationale.
"""

from __future__ import annotations

from lumen.shared.config.model_selection_runtime import (
    activate_llm_selection,
    llm_config_from_resolved,
    reset_llm_selection,
    resolve_llm_config_for_selection,
)

__all__ = [
    "activate_llm_selection",
    "llm_config_from_resolved",
    "reset_llm_selection",
    "resolve_llm_config_for_selection",
]

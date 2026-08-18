"""Private shared util — model-selection access for runtime code.

See ``lumen.shared._util.memory`` for the rationale.
"""

from __future__ import annotations

from lumen.shared.config.model_selection import (
    LLMSelection,
    apply_llm_selection_to_catalog,
    list_llm_options,
)

__all__ = ["LLMSelection", "apply_llm_selection_to_catalog", "list_llm_options"]

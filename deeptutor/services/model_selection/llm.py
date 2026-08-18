# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared.config.model_selection``.

The LLM model-selection helpers are owned by ``lumen/shared/config``.  This
module re-exports them for existing importers and tests only.
"""

from __future__ import annotations

from lumen.shared.config.model_selection import *  # noqa: F401,F403
from lumen.shared.config.model_selection import __all__  # noqa: F401

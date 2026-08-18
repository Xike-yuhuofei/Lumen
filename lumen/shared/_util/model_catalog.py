"""Private shared util — model-catalog access for runtime code.

See ``lumen.shared._util.memory`` for the rationale.
"""

from __future__ import annotations

from lumen.shared.config import get_model_catalog_service

__all__ = ["get_model_catalog_service"]

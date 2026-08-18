"""Private bridge to the runtime workspace-root resolution.

Kept as a private lumen util so ``mode.learn`` has no direct ``deeptutor``
import. The canonical path service now lives in ``lumen.shared._util.path_service``;
this single point forwards to it so consumers keep a stable import target.
"""

from __future__ import annotations

from .path_service import get_path_service  # noqa: F401

__all__ = ["get_path_service"]

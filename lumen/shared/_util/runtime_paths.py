"""Private bridge to the runtime workspace-root resolution.

Kept as a private lumen util so ``mode.learn`` has no direct ``deeptutor``
import. Until the namespace/App migration lands a real lumen-owned path
service, this single point forwards to the legacy runtime path service — the
only place that must change when the migration retires the bridge.
"""

from __future__ import annotations

from deeptutor.services.path_service import get_path_service  # noqa: F401

__all__ = ["get_path_service"]
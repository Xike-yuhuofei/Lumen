# ruff: noqa: F405
"""PathService — canonical implementation lives in ``lumen``."""

from __future__ import annotations

from lumen.shared._util.path_service import *  # noqa: F401,F403

__all__ = [
    "AgentModule",
    "ChatWorkspaceFeature",
    "PathService",
    "WorkspaceFeature",
    "get_path_service",
]

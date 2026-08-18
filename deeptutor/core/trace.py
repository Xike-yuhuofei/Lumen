# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.stream.trace``.

The trace metadata helpers are owned by ``lumen/runtime/stream``.  This module
re-exports them for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.stream.trace import *  # noqa: F401,F403

__all__ = [
    "build_trace_metadata",
    "derive_trace_metadata",
    "merge_trace_metadata",
    "new_call_id",
]

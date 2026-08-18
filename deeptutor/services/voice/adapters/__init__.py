# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.shared._util.voice.adapters``.

The Voice service is owned by ``lumen.shared._util.voice.adapters`` (canonical). This
package re-exports every symbol for existing importers and tests only.
"""

from __future__ import annotations

import lumen.shared._util.voice.adapters as _canon


def __getattr__(name: str):
    return getattr(_canon, name)


__all__ = list(_canon.__all__)

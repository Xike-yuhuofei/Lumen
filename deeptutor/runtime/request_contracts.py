# ruff: noqa: F405
"""Deprecated compatibility facade — see ``lumen.runtime.request_contracts``.

The request-contract validators are owned by ``lumen/runtime``.  This module
re-exports them for existing importers and tests only.
"""

from __future__ import annotations

from lumen.runtime.request_contracts import *  # noqa: F401,F403
from lumen.runtime.request_contracts import __all__  # noqa: F401

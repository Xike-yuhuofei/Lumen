"""Private shared util — notebook-manager access for runtime code.

See ``lumen.shared._util.memory`` for the rationale: runtime code reaches
shared services through the private ``_util`` channel.
"""

from __future__ import annotations

from lumen.shared.notebook.service import RecordType, get_notebook_manager

__all__ = ["RecordType", "get_notebook_manager"]

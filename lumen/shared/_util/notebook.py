"""Private shared util — notebook-manager access for runtime code.

See ``lumen.shared._util.memory`` for the rationale: runtime code reaches
shared services through the private ``_util`` channel.  Names are read
through lazily so a test patching the source module still takes effect.
"""

from __future__ import annotations

from lumen.shared.notebook import service as _service


def __getattr__(name: str):
    if name == "get_notebook_manager":
        return _service.get_notebook_manager
    if name == "RecordType":
        return _service.RecordType
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

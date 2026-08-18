"""Private shared util — sandbox artifact rendering for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the sandbox artifact helpers
through that private channel.  Names are read through lazily so a test
patching the source module still takes effect.
"""

from __future__ import annotations

from lumen.shared.sandbox import artifacts as _artifacts


def __getattr__(name: str):
    return getattr(_artifacts, name)

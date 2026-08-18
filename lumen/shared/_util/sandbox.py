"""Private shared util — sandbox access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the sandbox service and its
spec types through that private channel.  Names are read through lazily so a
test patching ``lumen.shared.sandbox`` still takes effect.
"""

from __future__ import annotations

from lumen.shared import sandbox as _sandbox


def __getattr__(name: str):
    return getattr(_sandbox, name)

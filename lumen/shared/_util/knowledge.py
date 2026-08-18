"""Private shared util — knowledge-base manifest access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the KB manifest constants and
renderers through that private channel.  Names are read through lazily so a
test patching the source module still takes effect.
"""

from __future__ import annotations

from lumen.shared.knowledge import manifest as _manifest


def __getattr__(name: str):
    return getattr(_manifest, name)

"""Private shared util — chat-params config access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the chat-params loader through
that private channel.  Names are read through lazily so a test patching the
source module still takes effect.
"""

from __future__ import annotations

from lumen.shared.config import loader as _loader


def __getattr__(name: str):
    return getattr(_loader, name)

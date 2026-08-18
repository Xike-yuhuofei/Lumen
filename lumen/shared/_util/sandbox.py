"""Private shared util — sandbox access for runtime code.

The plugin dependency gates allow runtime modules to import only
``lumen.shared._util.*``; this module routes the sandbox service and its
spec types through that private channel.
"""

from __future__ import annotations

from lumen.shared.sandbox import ExecRequest, Mount, ResourceLimits, get_sandbox_service

__all__ = ["ExecRequest", "Mount", "ResourceLimits", "get_sandbox_service"]

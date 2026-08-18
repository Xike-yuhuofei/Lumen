"""Private shared util — system settings access for runtime code.

Runtime modules may import this private module (per the plugin dependency
gates); the public definition stays in ``lumen.shared.config.runtime_settings``
and is re-exported here.
"""

from __future__ import annotations

from lumen.shared.config.runtime_settings import load_system_settings

__all__ = ["load_system_settings"]

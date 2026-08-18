"""Private shared util — agent parameter resolution.

Runtime code may import this private module (per the plugin dependency gates);
the public ``lumen.shared.config.loader.get_agent_params`` remains the
canonical definition and is re-exported here for runtime consumers.
"""

from __future__ import annotations

from lumen.shared.config.loader import get_agent_params

__all__ = ["get_agent_params"]

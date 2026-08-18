"""Private shared util — persona-service access for runtime code.

See ``lumen.shared._util.memory`` for the rationale.
"""

from __future__ import annotations

from lumen.shared.persona.service import (
    PersonaService,
    get_persona_service,
)

__all__ = ["PersonaService", "get_persona_service"]

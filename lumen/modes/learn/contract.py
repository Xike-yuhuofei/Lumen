"""Learn mode service contract (Phase 4).

The minimal stable interface a ``mode.learn`` consumer needs.  Deliberately
exposes only start / resume / handle_turn / get_state — never the underlying
``MasteryPathCapability`` or ``LearningService`` wholesale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LearnModeService(ABC):
    """The learner-facing surface of mastery-based tutoring."""

    @abstractmethod
    async def start(self, path_id: str) -> dict[str, Any]:
        """Create (or reload) a learner path and return its initial state."""
        ...

    @abstractmethod
    async def resume(self, path_id: str) -> dict[str, Any] | None:
        """Load an existing learner path state, or ``None`` if absent."""
        ...

    @abstractmethod
    async def handle_turn(self, context: Any, stream: Any) -> None:
        """Run one tutoring turn through the agent loop."""
        ...

    @abstractmethod
    async def get_state(self, path_id: str) -> dict[str, Any]:
        """Read the current learner state for ``path_id`` (empty dict if none)."""
        ...

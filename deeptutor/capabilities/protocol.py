"""Protocol shared by the chat loop and its loop capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from deeptutor.core.context import UnifiedContext


@dataclass(frozen=True, slots=True)
class PromptBlock:
    """One named prompt fragment contributed to the loop system prompt."""

    name: str
    content: str


class LoopCapability(Protocol):
    """Optional per-turn extension point for the chat agent loop.

    A loop capability reuses the *full* chat tool surface — every built-in,
    with the user's composer toggles respected exactly as in plain chat — and
    adds its own :attr:`owned_tools` on top when active. It does not curate or
    suppress the reused surface: a solve / mastery turn sees the same built-ins
    a chat turn would, plus the capability's own tools.

    Optional async ``pre_loop`` hook
    --------------------------------
    A capability MAY define::

        async def pre_loop(
            self, context, stream, *, usage=None
        ) -> PromptBlock | None: ...

    which the chat pipeline awaits **once, before the answer loop's first LLM
    call**, when the capability is active. Its returned block is folded into
    the loop's user-message seed (alongside the KB seed) so the answer loop
    treats it as grounding context for the turn. Use it for a bounded
    pre-pass that produces context the loop should have up front.

    This hook is **optional** and not part of the required structural surface:
    the pipeline reads it with a ``getattr(cap, "pre_loop", None)`` default, so
    plain capabilities that omit it are unaffected. ``usage`` is the turn's
    token tracker, passed so a pre-pass can fold its own LLM cost into the turn
    total.
    """

    name: str
    # Tools this capability registers and contributes when active (added on top
    # of chat's standard composition). Static — so the settings UI can group
    # them under their owning capability without a turn context.
    owned_tools: tuple[str, ...]

    def is_active(self, context: UnifiedContext) -> bool:
        """Whether this capability participates in the current turn."""

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        """Optional system prompt block contributed by the capability."""

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        """Inject server-owned private kwargs for this capability's tools."""

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        """Optional text appended to the initial user message seed."""


__all__ = ["LoopCapability", "PromptBlock"]

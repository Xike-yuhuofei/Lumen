"""Deterministic model seams for the Evolution Harness.

All providers in the harness are driven through the frozen ``Model`` contract
by an identical *seeded scripted model*, so the same input/tools/scripts replay
deterministically and identically across every provider — the core control
variable guarantee of the Runtime Benchmark v2.
"""

from __future__ import annotations

import random
from typing import Any

from lumen.evolution.contract import Model


def _tool_calls(msg: Any) -> list[dict[str, Any]]:
    """Normalise a model response into a list of requested tool calls."""
    if isinstance(msg, dict):
        for key in ("tool_calls", "function_calls"):
            calls = msg.get(key)
            if calls:
                return list(calls)
        return []
    return list(getattr(msg, "tool_calls", []) or [])


def _text(msg: Any) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        return str(msg.get("content") or msg.get("text") or "")
    return str(getattr(msg, "content", "") or "")


class ScriptedModel(Model):
    """Replays a script of steps, consumed linearly across the turn.

    Each step is either ``{"tool_calls": [{"name", "args"}]}`` (model requests
    tool calls) or a plain ``str`` final answer.  The last step repeats.  This
    makes every multi-round tool flow replay identically across providers.

    Records every message batch it sees into ``seen_messages`` for
    history-continuity / system-prompt-fidelity probes.
    """

    model_name: str = "scripted-seeded"

    def __init__(self, script: list[Any], *, seed: int | None = None) -> None:
        self._script = list(script)
        self._index = 0
        self._rng = random.Random(seed)
        self.seen_messages: list[list[dict[str, Any]]] = []
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[Any] | None = None,
        seed: int | None = None,
        **kwargs: Any,
    ) -> Any:
        self.seen_messages.append(list(messages))
        self.calls.append({"messages": list(messages)})
        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return step


__all__ = ["ScriptedModel", "_tool_calls", "_text"]

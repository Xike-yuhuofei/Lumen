"""Model gateway seam for the Phase 1 Teaching Optimization Loop.

Canonical home: ``lumen/cert``.

Every LLM-consuming component in the loop (Tutor, Learner Simulator, the three
Evaluators, Failure Reviewer/Diagnoser, Engineering Agent) talks to an
:class:`ModelGateway` — never directly to a provider. This gives a single,
auditable injection point so the *same* certification code runs against:

* the **real** Lumen LLM (:func:`lumen.shared._util.llm.complete`) — the very
  factory ``_RealLumenModel`` wires to in the production agent loop; and
* a deterministic :class:`ScriptedGateway` for tests, so the state machine /
  gates / data contract are proven without a live API.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: Convenience default for any LLM call that must never hang the loop.
DEFAULT_TIMEOUT_SECONDS = 60.0


class LLMCallError(RuntimeError):
    """Raised by a gateway when the underlying model call fails at runtime."""


class ModelGateway(Protocol):
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        label: str = "call",
    ) -> str: ...


@dataclass(slots=True)
class RealLumenGateway:
    """Real Lumen LLM via ``lumen.shared._util.llm.complete``.

    This is the same unified factory the production tutor model uses; it honors
    the active model profile / env credentials (``<BINDING>_API_KEY``).
    """

    timeout: float = DEFAULT_TIMEOUT_SECONDS
    model: str | None = None
    binding: str | None = None
    base_url: str | None = None
    api_key: str | None = None

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        label: str = "call",
    ) -> str:
        from lumen.shared._util.llm import complete

        kwargs: dict[str, Any] = {}
        if self.model:
            kwargs["model"] = self.model
        if self.binding:
            kwargs["binding"] = self.binding
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key
        try:
            return await asyncio.wait_for(
                complete(
                    user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ),
                timeout=self.timeout,
            )
        except TimeoutError as exc:
            raise LLMCallError(f"{label} timed out") from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("RealLumenGateway %s failed: %s", label, exc)
            raise LLMCallError(f"{label} failed: {exc}") from exc


@dataclass(slots=True)
class ScriptedGateway:
    """Deterministic, scripted gateway for tests.

    Maps a caller-provided ``label`` to an ordered list of canned responses.
    Raises :class:`LLMCallError` when a label has no canned response assigned,
    so tests can prove the INVALID / recovery path without a live API.
    """

    script: dict[str, list[str]] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    on_call: Any = None  # optional callback (label, system_prompt, user_prompt) -> None

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        label: str = "call",
    ) -> str:
        if self.on_call is not None:
            self.on_call(label, system_prompt, user_prompt)
        responses = self.script.get(label)
        if not responses:
            raise LLMCallError(f"ScriptedGateway: no canned response for label={label!r}")
        idx = self._counters.get(label, 0)
        if idx >= len(responses):
            idx = len(responses) - 1  # repeat last response
        self._counters[label] = idx + 1
        return responses[idx]


@dataclass(slots=True)
class ModelRoute:
    """Route a label prefix to a specific model gateway (real provider)."""

    label_prefix: str
    gateway: Any


class MultiModelGateway:
    """Routes each LLM role (tutor / learner / evaluator_* / diagnosis /
    engineering) to a different real model, so one certification can span
    several providers while the rest of the subsystem stays gateway-agnostic.

    The longest matching label prefix wins; unrecognized labels use ``default``.
    This is used by the real run (criterion #10) to honor the operator's
    per-role model selection, e.g. Tutor on Gitee GLM-5.2 and the Learner
    Simulator + Evaluators on DeepSeek deepseek-v4-flash.
    """

    def __init__(
        self,
        routes: list[ModelRoute] | None = None,
        default: Any | None = None,
    ) -> None:
        self._routes = sorted(routes or [], key=lambda r: len(r.label_prefix), reverse=True)
        self._default = default

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        label: str = "call",
    ) -> str:
        gateway = self._default
        for route in self._routes:
            if label.startswith(route.label_prefix):
                gateway = route.gateway
                break
        if gateway is None:
            raise LLMCallError(f"MultiModelGateway: no route and no default for label={label!r}")
        return await gateway.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            label=label,
        )


__all__ = ["ModelGateway", "RealLumenGateway", "ScriptedGateway", "MultiModelGateway", "ModelRoute", "LLMCallError"]
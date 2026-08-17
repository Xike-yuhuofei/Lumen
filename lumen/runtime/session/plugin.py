"""Runtime adapter plugin — bridge existing ``deeptutor`` session store and
turn runtime into the Plugin Kernel via :class:`SessionService`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.runtime.session.contract import SessionService


class _SessionServiceAdapter(SessionService):
    """Wraps ``deeptutor.services.session`` (store + turn runtime) as one
    :class:`SessionService`."""

    def __init__(self) -> None:
        self._store: Any = None
        self._runtime: Any = None

    def _ensure_loaded(self) -> None:
        if self._store is not None:
            return
        # Reuse the process-global TurnRuntimeManager (keyed by store db_path)
        # so the adapter shares the same turn executions as the rest of the
        # runtime instead of spinning up a private one.
        from deeptutor.services.session.turn_runtime import get_turn_runtime_manager

        self._runtime = get_turn_runtime_manager()
        self._store = self._runtime.store

    async def ensure_session(self, session_id: str | None = None) -> dict[str, Any]:
        self._ensure_loaded()
        return await self._store.ensure_session(session_id)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return await self._store.get_session(session_id)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return await self._store.get_turn(turn_id)

    async def start_turn(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self._ensure_loaded()
        return await self._runtime.start_turn(payload)

    async def cancel_turn(self, turn_id: str) -> bool:
        self._ensure_loaded()
        return await self._runtime.cancel_turn(turn_id)

    async def subscribe_turn(
        self, turn_id: str, after_seq: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        self._ensure_loaded()
        return self._runtime.subscribe_turn(turn_id, after_seq)

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return await self._store.get_messages(session_id)

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        **kwargs: Any,
    ) -> int | str:
        self._ensure_loaded()
        return await self._store.add_message(
            session_id, role, content, capability=capability, **kwargs
        )

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        self._ensure_loaded()
        return await self._store.update_turn_status(turn_id, status, error)


class SessionPlugin(Plugin):
    """Provide the session store and turn runtime as ``runtime.session``."""

    manifest = PluginManifest(id="runtime.session", provides=["runtime.session"])

    async def setup(self, ctx: PluginContext) -> None:
        ctx.provide("runtime.session", _SessionServiceAdapter())

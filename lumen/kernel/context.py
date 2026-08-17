"""Plugin contexts with reversible registrations and parent lookup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from lumen.kernel.effects import DisposalStack
from lumen.kernel.plugin import PluginContext as PluginContextBase
from lumen.kernel.registry import ServiceRegistry

Cleanup = Callable[[], Any]


class PluginContext(PluginContextBase):
    """Concrete plugin context.

    Lookup walks up the parent chain, so a child reads (and may shadow)
    anything its ancestors published. ``child(shared=True)`` instead shares
    this context's registry: writes land in one flat namespace while undo
    callbacks stay scoped to the writing context. ``Bootstrap`` gives every
    plugin a shared child of the root, so sibling plugins see each other's
    services and the root can read them too.

    Disposal is async: children are torn down first (most dependent first),
    then this context's undo callbacks run in reverse registration order,
    awaiting async cleanups and cancelled background tasks along the way.
    """

    def __init__(
        self,
        parent: PluginContext | None = None,
        *,
        registry: ServiceRegistry | None = None,
    ) -> None:
        self._parent = parent
        self._registry = registry if registry is not None else ServiceRegistry()
        self._disposal = DisposalStack()
        self._children: list[PluginContext] = []
        self._disposed = False
        if parent is not None:
            parent._children.append(self)
            self._disposal.push(lambda: parent._detach_child(self))

    def _detach_child(self, child: PluginContext) -> None:
        if child in self._children:
            self._children.remove(child)

    def provide(self, name: str, instance: object) -> None:
        if self._disposed:
            raise RuntimeError("context disposed")
        if self._registry.has(name):
            raise RuntimeError(f"duplicate provider for {name}")
        self._registry.provide(name, instance)
        self._disposal.push(lambda: self._registry.remove(name))

    def require(self, name: str) -> object:
        context: PluginContext | None = self
        while context is not None:
            if context._registry.has(name):
                return context._registry.require(name)
            context = context._parent
        raise LookupError(f"service not found: {name}")

    def optional(self, name: str) -> object | None:
        context: PluginContext | None = self
        while context is not None:
            if context._registry.has(name):
                return context._registry.optional(name)
            context = context._parent
        return None

    def child(self, *, shared: bool = False) -> PluginContext:
        if self._disposed:
            raise RuntimeError("context disposed")
        if shared:
            return PluginContext(parent=self, registry=self._registry)
        return PluginContext(parent=self)

    def on_dispose(self, callback: Cleanup) -> None:
        if self._disposed:
            raise RuntimeError("context disposed")
        self._disposal.push(callback)

    def track_task(self, task: asyncio.Task[object]) -> None:
        """Cancel a background task on disposal and wait for it to finish."""

        async def _cancel_and_await() -> None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        self.on_dispose(_cancel_and_await)

    async def dispose(self) -> None:
        """Tear down this context, its children, and every registration.

        Children go first (most dependent first) and undo callbacks run in
        reverse registration order, so every effect is reversible. Disposal
        is idempotent.
        """
        if self._disposed:
            return
        self._disposed = True
        for child in reversed(list(self._children)):
            await child.dispose()
        await self._disposal.dispose()

    @property
    def disposed(self) -> bool:
        return self._disposed

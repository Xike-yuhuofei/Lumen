"""Plugin contract — the only interface plugins and the kernel agree on."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: A cleanup callback: sync (returns None) or async (returns an awaitable).
Cleanup = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class PluginManifest:
    id: str
    api_version: int = 1
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)


class PluginContext(ABC):
    @abstractmethod
    def provide(self, name: str, instance: object) -> None:
        raise NotImplementedError

    @abstractmethod
    def require(self, name: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def optional(self, name: str) -> object | None:
        raise NotImplementedError

    @abstractmethod
    def child(self) -> PluginContext:
        raise NotImplementedError

    @abstractmethod
    async def dispose(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_dispose(self, callback: Cleanup) -> None:
        raise NotImplementedError

    @abstractmethod
    def track_task(self, task: asyncio.Task[object]) -> None:
        raise NotImplementedError


class Plugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    async def setup(self, ctx: PluginContext) -> None:
        raise NotImplementedError

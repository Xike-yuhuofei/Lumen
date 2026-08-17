"""Reversible effects for plugin registration and runtime cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
from typing import Any

#: A cleanup callback: sync (returns None) or async (returns an awaitable).
Cleanup = Callable[[], Any]


class DisposalStack:
    """Run cleanup callbacks in reverse registration order.

    Callbacks may be sync or async; async results are awaited inline.
    ``dispose`` is idempotent, and new pushes are rejected once disposal
    has started.
    """

    def __init__(self) -> None:
        self._stack: list[Cleanup] = []
        self._lock = asyncio.Lock()
        self._disposed = False

    def push(self, undo: Cleanup) -> None:
        if self._disposed:
            raise RuntimeError("disposal stack already disposed")
        self._stack.append(undo)

    async def dispose(self) -> None:
        if self._disposed:
            return
        async with self._lock:
            if self._disposed:
                return
            self._disposed = True
            while self._stack:
                undo = self._stack.pop()
                try:
                    result = undo()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    pass

    @property
    def disposed(self) -> bool:
        return self._disposed


class BackgroundTask:
    def __init__(self, task: asyncio.Task[Any]) -> None:
        self._task = task

    def cancel(self) -> None:
        self._task.cancel()

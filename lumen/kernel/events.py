"""Minimal event bus with reversible subscriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., None]]] = {}

    def subscribe(self, event: str, listener: Callable[..., None]) -> Callable[[], None]:
        bucket = self._listeners.setdefault(event, [])
        bucket.append(listener)

        def unsubscribe() -> None:
            self.unsubscribe(event, listener)

        return unsubscribe

    def unsubscribe(self, event: str, listener: Callable[..., None]) -> None:
        bucket = self._listeners.get(event)
        if not bucket:
            return
        if listener in bucket:
            bucket.remove(listener)
        if not bucket:
            self._listeners.pop(event, None)

    def publish(self, event: str, *args: Any, **kwargs: Any) -> None:
        for listener in list(self._listeners.get(event, [])):
            listener(*args, **kwargs)

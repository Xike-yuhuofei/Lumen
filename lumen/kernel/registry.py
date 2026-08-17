"""Service registry for plugin-provided contracts."""

from __future__ import annotations

from collections.abc import Mapping


class ServiceRegistry:
    """Store service contract -> provider instance mappings.

    The registry itself is intentionally small. Reversibility is handled by the
    owning context, which records undo callbacks for every registration.
    """

    def __init__(self) -> None:
        self._services: dict[str, object] = {}

    def provide(self, name: str, instance: object) -> None:
        if name in self._services:
            raise RuntimeError(f"service already provided: {name}")
        self._services[name] = instance

    def require(self, name: str) -> object:
        try:
            return self._services[name]
        except KeyError as exc:
            raise LookupError(name) from exc

    def optional(self, name: str) -> object | None:
        return self._services.get(name)

    def remove(self, name: str) -> None:
        self._services.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._services

    def snapshot(self) -> Mapping[str, object]:
        return dict(self._services)

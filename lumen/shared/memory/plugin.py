"""Memory store adapter plugin."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.contract import MemoryService


class _MemoryServiceAdapter(MemoryService):
    """Wraps ``lumen.shared.memory.store.MemoryStore``."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def read(self, layer: str, key: str) -> dict[str, Any] | None:
        doc = await asyncio_to_thread(self._store.read_doc, layer, key)
        return {"title": doc.title, "sections": doc.sections}

    async def read_concat(self) -> str:
        return await asyncio_to_thread(self._store.read_l3_concat)

    async def overwrite(self, layer: str, key: str, content: str) -> None:
        await self._store.overwrite_doc(layer, key, content)

    async def delete_entry(self, layer: str, key: str, entry_id: str) -> bool:
        return await self._store.delete_entry(layer, key, entry_id)

    def overview(self) -> list[dict[str, Any]]:
        return [{"layer": o.layer, "key": o.key, "title": o.title} for o in self._store.overview()]


async def asyncio_to_thread(func, *args):
    import asyncio

    return await asyncio.to_thread(func, *args)


class MemoryPlugin(Plugin):
    """Provide the memory store as ``memory``."""

    manifest = PluginManifest(id="memory", provides=["memory"])

    async def setup(self, ctx: PluginContext) -> None:
        from lumen.shared.memory.store import get_memory_store

        ctx.provide("memory", _MemoryServiceAdapter(get_memory_store()))

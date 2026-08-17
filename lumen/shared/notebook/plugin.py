"""Notebook service adapter plugin."""

from __future__ import annotations

from typing import Any

from lumen.kernel.plugin import Plugin, PluginContext, PluginManifest
from lumen.shared.contract import NotebookService


class _NotebookServiceAdapter(NotebookService):
    """Wraps ``deeptutor.services.notebook.service.NotebookManager``."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def create(
        self, name: str, description: str = "", color: str = "#3B82F6", icon: str = "book"
    ) -> dict[str, Any]:
        return self._manager.create_notebook(name, description=description, color=color, icon=icon)

    def list(self) -> list[dict[str, Any]]:
        return self._manager.list_notebooks()

    def get(self, notebook_id: str) -> dict[str, Any] | None:
        return self._manager.get_notebook(notebook_id)

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: str,
        title: str,
        user_query: str,
        output: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        kb_name: str | None = None,
    ) -> dict[str, Any] | None:
        return self._manager.add_record(
            notebook_ids,
            record_type,
            title,
            user_query,
            output,
            summary=summary,
            metadata=metadata,
            kb_name=kb_name,
        )

    def get_records(
        self, notebook_id: str, record_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return self._manager.get_records(notebook_id, record_ids)

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        return self._manager.remove_record(notebook_id, record_id)


class NotebookPlugin(Plugin):
    """Provide the notebook manager as ``notebook``."""

    manifest = PluginManifest(id="notebook", provides=["notebook"])

    async def setup(self, ctx: PluginContext) -> None:
        from deeptutor.services.notebook.service import get_notebook_manager

        ctx.provide("notebook", _NotebookServiceAdapter(get_notebook_manager()))

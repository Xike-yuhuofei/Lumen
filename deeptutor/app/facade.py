"""Stable application-layer facade for DeepTutor entry points."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, AsyncIterator

from deeptutor.services.notebook import get_notebook_manager
from deeptutor.services.session import get_session_store, get_turn_runtime_manager


@dataclass(slots=True)
class TurnRequest:
    """Stable turn payload used by adapters such as the CLI package."""

    content: str
    capability: str = "chat"
    session_id: str | None = None
    tools: list[str] = field(default_factory=list)
    knowledge_bases: list[str] = field(default_factory=list)
    language: str = "en"
    config: dict[str, Any] = field(default_factory=dict)
    notebook_references: list[dict[str, Any]] = field(default_factory=list)
    history_references: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "capability": self.capability,
            "session_id": self.session_id,
            "tools": list(self.tools),
            "knowledge_bases": list(self.knowledge_bases),
            "language": self.language,
            "config": dict(self.config),
            "notebook_references": list(self.notebook_references),
            "history_references": list(self.history_references),
            "attachments": list(self.attachments),
            "skills": list(self.skills),
        }


@dataclass(slots=True)
class CapabilityAvailability:
    """Availability result for optional capabilities."""

    name: str
    available: bool
    install_hint: str = ""


class DeepTutorApp:
    """Facade around runtime, session, notebook, and capability contracts."""

    def __init__(self) -> None:
        self.runtime = get_turn_runtime_manager()
        self.store = get_session_store()
        self.notebooks = get_notebook_manager()

    def resolve_capability(self, value: str | None) -> str:
        """Map a request onto a canonical facade capability.

        ``mode.learn`` is the only canonical Learn id; the legacy
        ``mastery_path`` / ``mastery`` names are accepted as compatibility
        aliases and rewritten through the single canonical mapping in
        :func:`lumen.compat.resolve_learn_mode`.  Generic turns resolve to
        ``chat``.  Unknown names are rejected.
        """
        from lumen.compat import resolve_learn_mode

        requested = str(value or "chat").strip() or "chat"
        mode = resolve_learn_mode(requested)
        if mode == "mode.learn":
            return "mode.learn"
        if mode == "chat":
            return "chat"
        raise ValueError(
            f"Unknown capability `{requested}`. Available: chat, mode.learn"
        )

    @staticmethod
    def _chat_manifest() -> dict[str, Any]:
        """Canonical App-layer chat manifest.

        ``chat`` is the only generic capability.  Its manifest is the source
        of truth defined here for the App contract surface
        (``get_capability_contract*``).  ``tools_used`` is pulled lazily from
        the chat pipeline so the facade's module import stays lightweight.
        """
        from deeptutor.agents.chat.agentic_pipeline import CHAT_OPTIONAL_TOOLS
        from deeptutor.i18n.metadata_i18n import capability_description_i18n
        from deeptutor.runtime.request_contracts import get_capability_request_schema

        manifest = {
            "name": "chat",
            "description": (
                "Agentic chat: an exploring agent loop with tools, followed by "
                "a respond stage that streams the answer."
            ),
            "description_i18n": capability_description_i18n(
                "chat",
                "Agentic chat: an exploring agent loop with tools, followed by "
                "a respond stage that streams the answer.",
            ),
            "stages": ["exploring", "responding"],
            "tools_used": list(CHAT_OPTIONAL_TOOLS),
            "cli_aliases": ["chat"],
            "request_schema": get_capability_request_schema("chat"),
            "config_defaults": {},
        }
        return manifest

    def get_capability_contracts(self) -> list[dict[str, Any]]:
        chat = self._chat_manifest()
        return [
            {
                **chat,
                "availability": asdict(self.get_capability_availability(chat["name"])),
            }
        ]

    def get_capability_contract(self, value: str) -> dict[str, Any]:
        resolved = self.resolve_capability(value)
        if resolved == "mode.learn":
            # Canonical Learn exposes a stable canonical snapshot.
            return {
                "name": "mode.learn",
                "description": "Canonical guided-learning (Learn) mode.",
                "description_i18n": {},
                "stages": [],
                "tools_used": [],
                "cli_aliases": ["mastery_path", "mastery"],
                "request_schema": {},
                "config_defaults": {},
                "availability": asdict(self.get_capability_availability(resolved)),
            }
        chat = self._chat_manifest()
        return {
            **chat,
            "availability": asdict(self.get_capability_availability(chat["name"])),
        }

    def get_capability_availability(self, capability: str) -> CapabilityAvailability:
        resolved = self.resolve_capability(capability)
        return CapabilityAvailability(name=resolved, available=True)

    async def start_turn(
        self, request: TurnRequest | dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(request, dict):
            request = TurnRequest(**request)
        resolved_capability = self.resolve_capability(request.capability)
        session, turn = await self.runtime.start_turn(
            {
                **request.to_payload(),
                "capability": resolved_capability,
            }
        )
        await self.store.update_session_preferences(
            session["id"],
            {
                "language": request.language,
                "notebook_references": request.notebook_references,
                "history_references": request.history_references,
            },
        )
        return session, turn

    async def stream_turn(self, turn_id: str, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        async for item in self.runtime.subscribe_turn(turn_id, after_seq=after_seq):
            yield item

    async def cancel_turn(self, turn_id: str) -> bool:
        return await self.runtime.cancel_turn(turn_id)

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Deliver the user's reply to a turn paused on ``ask_user``."""
        return await self.runtime.submit_user_reply(turn_id, text=text, answers=answers)

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await self.runtime.regenerate_last_turn(session_id, overrides=overrides)

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return await self.store.list_sessions(limit=limit, offset=offset)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self.store.get_session_with_messages(session_id)

    async def rename_session(self, session_id: str, title: str) -> bool:
        return await self.store.update_session_title(session_id, title)

    async def delete_session(self, session_id: str) -> bool:
        return await self.store.delete_session(session_id)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        return await self.store.get_active_turn(session_id)

    def list_notebooks(self) -> list[dict[str, Any]]:
        return self.notebooks.list_notebooks()

    def create_notebook(
        self,
        name: str,
        description: str = "",
        *,
        color: str = "#3B82F6",
        icon: str = "book",
    ) -> dict[str, Any]:
        return self.notebooks.create_notebook(
            name=name,
            description=description,
            color=color,
            icon=icon,
        )

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        return self.notebooks.get_notebook(notebook_id)

    def add_record(self, **kwargs: Any) -> dict[str, Any]:
        return self.notebooks.add_record(**kwargs)

    def update_record(
        self, notebook_id: str, record_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.notebooks.update_record(notebook_id, record_id, **kwargs)

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        return self.notebooks.remove_record(notebook_id, record_id)

    def get_records_by_references(
        self, notebook_references: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.notebooks.get_records_by_references(notebook_references)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

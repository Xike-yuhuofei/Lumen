"""Who may drive the Codex OAuth lifecycle (issue #781).

These five endpoints act on the *caller's own* credentials — the store, the
model catalog, and the callback route are all resolved from owner scope — so
the administrator gate that used to sit on them was what left ordinary users
unable to use Codex at all: an owner-bound profile is never grantable, and
they could not sign in for themselves either.

"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.multi_user.models import CurrentUser, UserScope


class _Service:
    """Stand-in for the per-owner ``CodexOAuthService``."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_login(self) -> dict[str, Any]:
        self.calls.append("start")
        return {"operation_id": "op-1"}

    def public_status(self) -> dict[str, Any]:
        self.calls.append("status")
        return {"connection": "disconnected"}

    async def cancel_login(self) -> dict[str, Any]:
        self.calls.append("cancel")
        return {"connection": "disconnected"}

    async def logout(self) -> dict[str, Any]:
        self.calls.append("logout")
        return {"connection": "disconnected"}

    async def refresh_models(self) -> dict[str, Any]:
        self.calls.append("refresh")
        return {"connection": "connected"}

    async def set_reasoning_effort(
        self,
        model: str,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        self.calls.append(f"reasoning:{model}:{reasoning_effort}")
        return {"connection": "connected"}


def _user(uid: str, *, role: str, root) -> CurrentUser:
    return CurrentUser(
        id=uid,
        username=uid,
        role=role,
        scope=UserScope(kind="user", user_id=uid, root=root),
    )


@pytest.fixture
def client(tmp_path, monkeypatch) -> tuple[TestClient, _Service, dict[str, CurrentUser]]:
    service = _Service()
    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: service)
    current: dict[str, CurrentUser] = {
        "user": _user("u_alice", role="user", root=tmp_path / "alice")
    }
    monkeypatch.setattr(settings_router, "get_current_user", lambda: current["user"])

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1/settings")
    return TestClient(app), service, current

"""Regression tests for #481 and the auth-dep refactor.

When ``require_auth`` was declared as a sync ``def``, FastAPI dispatched it
through ``anyio.to_thread.run_sync``, which executes the function in a worker
thread under a *copy* of the request context. Any ``ContextVar.set`` inside
that thread is discarded when the thread returns, so the endpoint reads the
unset default, and the request-local path service silently falls back to the
admin workspace.

These tests pin the invariants that still hold in single-user mode:

1. ``require_auth`` and ``require_admin`` are declared ``async``.
2. ``_install_current_user`` is the single point of truth for the
   payload-to-CurrentUser mapping used by both HTTP and WebSocket entry
   points (``None`` → local admin, payload → ``user_from_token_payload``).
3. With ``AUTH_ENABLED=true`` and a valid token, the user ContextVar set
   inside ``require_auth`` is visible from inside the endpoint. Lumen runs as
   one local admin, so *any* authenticated payload resolves to that admin —
   even a token carrying ``role="user"``.
"""

from __future__ import annotations

import inspect

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def test_require_auth_is_async_def() -> None:
    from deeptutor.api.routers.auth import require_admin, require_auth

    assert inspect.iscoroutinefunction(require_auth), (
        "require_auth must be async — a sync dep is run in a threadpool whose "
        "ContextVar mutations don't propagate back to the endpoint. See #481."
    )
    assert inspect.iscoroutinefunction(require_admin), (
        "require_admin must be async for the same reason."
    )


def test_install_current_user_maps_none_to_local_admin() -> None:
    """``_install_current_user(None)`` is the AUTH_ENABLED=false branch
    for both HTTP and WS deps. It must install the local admin user so
    that ``get_current_path_service()`` resolves to the admin workspace
    rather than silently falling back through the None path."""
    from deeptutor.api.routers.auth import _install_current_user
    from lumen.shared._util.user import (
        LOCAL_ADMIN_ID,
        LOCAL_ADMIN_USERNAME,
        get_current_user_or_none,
        reset_current_user,
    )

    token = _install_current_user(None)
    try:
        user = get_current_user_or_none()
        assert user is not None
        assert user.id == LOCAL_ADMIN_ID
        assert user.username == LOCAL_ADMIN_USERNAME
        assert user.role == "admin"
        assert user.scope.kind == "admin"
    finally:
        reset_current_user(token)


def test_install_current_user_maps_payload_to_local_admin() -> None:
    """``_install_current_user(payload)`` resolves to the single local admin.

    Single-user mode: every authenticated identity is the local deployment
    account, so a token carrying ``role="user"`` still maps to the admin
    user (id/username/role and an ``admin`` scope), never a per-user scope.
    """
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.services.auth import TokenPayload
    from lumen.shared._util.user import (
        LOCAL_ADMIN_ID,
        LOCAL_ADMIN_USERNAME,
        get_current_user_or_none,
        reset_current_user,
    )

    token = _install_current_user(TokenPayload(username="alice", role="user", user_id="u_alice"))
    try:
        user = get_current_user_or_none()
        assert user is not None
        assert user.id == LOCAL_ADMIN_ID
        assert user.username == LOCAL_ADMIN_USERNAME
        assert user.role == "admin"
        assert user.scope.kind == "admin"
    finally:
        reset_current_user(token)


def test_local_admin_token_payload_matches_local_admin_user() -> None:
    """The synthetic admin TokenPayload returned by ``require_admin`` when
    AUTH_ENABLED=false must use the same identity constants as
    ``local_admin_user()`` — drift between the two reintroduces the kind
    of dual-source-of-truth bug that #481 lived in."""
    from deeptutor.api.routers.auth import _local_admin_token_payload
    from lumen.shared._util.user import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME, local_admin_user

    tp = _local_admin_token_payload()
    user = local_admin_user()
    assert tp.username == LOCAL_ADMIN_USERNAME == user.username
    assert tp.user_id == LOCAL_ADMIN_ID == user.id
    assert tp.role == "admin" == user.role


def test_require_auth_propagates_contextvar_to_endpoint(monkeypatch) -> None:
    """End-to-end: a valid token through require_auth makes the installed
    current user visible to the endpoint, even when the token says
    ``role="user"`` — single-user mode maps it to the local admin."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload
    from lumen.shared._util.user import (
        LOCAL_ADMIN_ID,
        LOCAL_ADMIN_USERNAME,
        get_current_user_or_none,
    )

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        if user is None:
            return {"seen": None}
        return {"seen": user.username, "role": user.role, "scope_kind": user.scope.kind}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["seen"] == LOCAL_ADMIN_USERNAME, (
        "Endpoint should observe the current user set inside require_auth. "
        "If this returns None the dependency is being run in a threadpool and "
        "the ContextVar mutation is discarded — see #481. In single-user mode a "
        "role=user payload resolves to the local admin, not a per-user scope."
    )
    assert body["role"] == "admin"
    assert body["scope_kind"] == "admin"
    assert body["seen"] != "alice"


def test_require_auth_propagates_admin_contextvar_to_endpoint(monkeypatch) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.services.auth import TokenPayload
    from lumen.shared._util.user import get_current_user_or_none

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="root", role="admin", user_id="u_root"),
    )

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        return {"role": None if user is None else user.role}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == {"role": "admin"}

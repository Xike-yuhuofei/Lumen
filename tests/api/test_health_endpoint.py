"""Tests for the production liveness/readiness probe ``/api/v1/health``.

The endpoint is intentionally unauthenticated so orchestrators (systemd /
launchd / Docker HEALTHCHECK / k8s) can probe it without credentials.  It must
never leak credentials, configuration, or provider secrets — only service
identity, version, and coarse readiness booleans.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from lumen.app.api import main as api_main


class _FakeStore:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    async def ping(self) -> bool:
        return self._ok


def test_health_reports_ready_when_kernel_booted_and_storage_ok(
    monkeypatch,
) -> None:
    """A booted kernel + reachable storage must report ``status == ok``."""

    class _BootedApp:
        state = type("S", (), {"lumen_root": object()})()

    monkeypatch.setattr(api_main.app, "state", _BootedApp().state)
    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=True),
    )

    client = TestClient(api_main.app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["kernel"] == "booted"
    assert body["storage"] == "ok"
    assert isinstance(body["version"], str) and body["version"]
    assert body["service"]


def test_health_degraded_when_kernel_not_booted(monkeypatch) -> None:
    """Without a booted kernel the probe must report ``degraded``, not crash."""
    monkeypatch.setattr(api_main.app, "state", type("S", (), {"lumen_root": None})())
    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=True),
    )

    client = TestClient(api_main.app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["kernel"] == "not_booted"


def test_health_degraded_when_storage_unreachable(monkeypatch) -> None:
    """An unreachable SQLite store must degrade readiness but stay 200."""
    monkeypatch.setattr(api_main.app, "state", type("S", (), {"lumen_root": object()})())
    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=False),
    )

    client = TestClient(api_main.app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["storage"] == "error"

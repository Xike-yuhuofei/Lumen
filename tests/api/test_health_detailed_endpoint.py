"""Tests for the Production Ops monitoring probe ``/api/v1/health/detailed``.

The detailed probe is unauthenticated (operators + orchestrators poll it for
SLI/SLO, capacity and telemetry health) and must expose only aggregated
counters/rates/sizes — never user content, prompts, responses or credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from lumen.app.api import main as api_main
from lumen.shared._util.observability import increment, reset_metrics


class _FakeStore:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    async def ping(self) -> bool:
        return self._ok


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root
        (root / "user" / "logs" / "telemetry").mkdir(parents=True, exist_ok=True)
        (root / "user" / "logs" / "metrics").mkdir(parents=True, exist_ok=True)
        (root / "knowledge_bases").mkdir(parents=True, exist_ok=True)

    @property
    def workspace_root(self) -> Path:
        return self._root

    def get_user_root(self) -> Path:
        return self._root / "user"

    def get_logs_dir(self) -> Path:
        return self._root / "user" / "logs"

    def get_knowledge_bases_root(self) -> Path:
        return self._root / "knowledge_bases"


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_metrics()
    yield
    reset_metrics()


def test_health_detailed_ok(monkeypatch, tmp_path: Path) -> None:
    reset_metrics()
    increment("turn.completed", 100)
    increment("llm.total", 100)
    increment("tool.total", 20)

    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=True),
    )
    monkeypatch.setattr(
        "lumen.shared._util.path_service.get_path_service",
        lambda: _FakePathService(tmp_path),
    )

    client = TestClient(api_main.app)
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["healthy"] is True
    assert body["version"]
    assert body["service"]
    assert body["sli"]["status"] == "ok"
    slis = body["sli"]["slis"]
    assert slis["turn"]["total"] == 100
    assert slis["llm"]["total"] == 100
    assert slis["persistence"]["status"] == "ok"
    assert body["telemetry"]["ok"] is True
    assert body["capacity"]["within_capacity"] is True
    assert "data_total" in body["capacity"]["bytes"]


def test_health_detailed_persistence_failure_is_critical(monkeypatch, tmp_path: Path) -> None:
    reset_metrics()
    increment("turn.completed", 10)
    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=False),
    )
    monkeypatch.setattr(
        "lumen.shared._util.path_service.get_path_service",
        lambda: _FakePathService(tmp_path),
    )
    client = TestClient(api_main.app)
    body = client.get("/api/v1/health/detailed").json()
    assert body["status"] == "critical"
    assert body["healthy"] is False
    assert body["sli"]["slis"]["persistence"]["status"] == "critical"


def test_health_detailed_never_leaks_sensitive_fields(monkeypatch, tmp_path: Path) -> None:
    """The probe must not expose secrets/keys/user content anywhere."""
    reset_metrics()
    increment("turn.failed", 1)
    monkeypatch.setattr(
        "lumen.runtime.session.sqlite_store.get_sqlite_session_store",
        lambda: _FakeStore(ok=True),
    )
    monkeypatch.setattr(
        "lumen.shared._util.path_service.get_path_service",
        lambda: _FakePathService(tmp_path),
    )
    body = TestClient(api_main.app).get("/api/v1/health/detailed").json()
    import json

    blob = json.dumps(body).lower()
    for token in ("api_key", "sk-", "password", "secret", "bearer", "token=", "prompt", "content["):
        assert token not in blob, f"detailed health leaked sensitive token: {token}"

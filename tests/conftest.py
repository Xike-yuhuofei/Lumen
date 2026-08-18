"""
Root conftest — shared fixtures for the entire test suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lumen.runtime.context import Attachment, UnifiedContext
from lumen.runtime.stream.bus import StreamBus

# ---------------------------------------------------------------------------
# Multi-user legacy migration guard
# ---------------------------------------------------------------------------


def _tree_snapshot(root: Path) -> frozenset[str]:
    if not root.is_dir():
        return frozenset()
    return frozenset(str(path) for path in root.rglob("*") if path.is_file())


#: Captured at import time — before any test can monkeypatch the roots — so the
#: guard below always watches the developer's real tree, whatever a test does.
_REAL_OWNER_SECRET_TREES: tuple[Path, ...] = ()
try:  # pragma: no cover - import-time wiring
    from lumen.shared._util.user import SYSTEM_ROOT as _REAL_SYSTEM_ROOT

    _REAL_OWNER_SECRET_TREES = (
        _REAL_SYSTEM_ROOT / "user-secrets",
        _REAL_SYSTEM_ROOT / "user-mcp",
    )
except Exception:  # pragma: no cover
    pass


@pytest.fixture(autouse=True)
def _guard_real_owner_secrets():
    """A test must never write into the real per-account state trees.

    These hold OAuth refresh tokens and MCP credentials. A test that redirects
    ``ADMIN_WORKSPACE_ROOT`` but forgets ``SYSTEM_ROOT`` — or that calls
    ``monkeypatch.undo()`` and so reverts a fixture's redirection — lands here,
    and without this guard the failure is silent: the test passes while the
    developer's tree quietly grows files named after fixture users.
    """
    before = {root: _tree_snapshot(root) for root in _REAL_OWNER_SECRET_TREES}
    yield
    for root, snapshot in before.items():
        added = _tree_snapshot(root) - snapshot
        if added:
            for path in added:
                Path(path).unlink(missing_ok=True)
            pytest.fail(
                "test wrote into the real per-account state tree "
                f"{root}: {sorted(added)}. Redirect paths.SYSTEM_ROOT and "
                "paths.ADMIN_WORKSPACE_ROOT."
            )


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """Hide residual provider environment variables from every test."""
    yield


# ---------------------------------------------------------------------------
# StreamBus
# ---------------------------------------------------------------------------


@pytest.fixture
def stream_bus() -> StreamBus:
    """Fresh StreamBus for one test."""
    return StreamBus()


# ---------------------------------------------------------------------------
# UnifiedContext
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_context() -> UnifiedContext:
    """Context with just a user message."""
    return UnifiedContext(
        session_id="test-session",
        user_message="Hello",
        language="en",
    )


@pytest.fixture
def rich_context() -> UnifiedContext:
    """Context with attachments, tools, KB, and metadata."""
    return UnifiedContext(
        session_id="test-session",
        user_message="Explain RAG",
        conversation_history=[
            {"role": "user", "content": "What is AI?"},
            {"role": "assistant", "content": "AI is..."},
        ],
        enabled_tools=["rag", "web_search"],
        active_capability="chat",
        knowledge_bases=["my-kb"],
        attachments=[Attachment(type="image", url="https://img.png")],
        config_overrides={"temperature": 0.7},
        language="en",
        metadata={"turn_id": "t-1"},
    )


# ---------------------------------------------------------------------------
# SQLiteSessionStore (in-memory / tmp)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Temporary database file path."""
    return tmp_path / "test_chat.db"


@pytest.fixture
def sqlite_store(tmp_db_path: Path):
    """SQLiteSessionStore backed by a temp file."""
    from lumen.runtime.session.sqlite_store import SQLiteSessionStore

    return SQLiteSessionStore(db_path=tmp_db_path)


# ---------------------------------------------------------------------------
# Fake LLM helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm_config() -> MagicMock:
    """MagicMock mimicking LLMConfig with common defaults."""
    cfg = MagicMock()
    cfg.model = "gpt-4o-mini"
    cfg.max_tokens = 4096
    cfg.temperature = 0.7
    cfg.api_key = "sk-test"
    cfg.api_base = "https://api.openai.com/v1"
    return cfg

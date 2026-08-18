"""Shared fixtures for the Learn Evaluation tests.

Isolates the learner store and the teaching-graph SQLite db into a per-test
temp dir so every benchmark/scenario run is hermetic and repeatable.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.storage import LearningStore


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    """Point the learner store and the teaching-graph db at *tmp_path*."""

    def _init(self, root=None, **kwargs):
        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    monkeypatch.setattr(
        "lumen.modes.learn.adapters.graph_repository.default_graph_db_path",
        lambda: tmp_path / "graphs.db",
    )
    return tmp_path


@pytest.fixture
def store_root(tmp_path):
    """A dedicated root for an explicitly-constructed LearningStore."""
    return tmp_path

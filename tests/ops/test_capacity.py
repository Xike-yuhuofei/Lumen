"""Production Operations capacity tests."""

from __future__ import annotations

from pathlib import Path

from lumen.ops.capacity import (
    LogRetention,
    capacity_report,
    dir_size,
    retention_status,
    walk_sizes,
)


def test_dir_size_empty_path(tmp_path: Path) -> None:
    assert dir_size(tmp_path / "nonexistent") == 0
    assert dir_size(tmp_path) == 0


def test_dir_size_single_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert dir_size(f) == 5


def test_dir_size_recursive(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x" * 100)
    (tmp_path / "b.txt").write_text("y" * 50)
    assert dir_size(tmp_path) == 150


def test_retention_status(tmp_path: Path) -> None:
    (tmp_path / "telemetry").mkdir(parents=True)
    (tmp_path / "metrics").mkdir()
    (tmp_path / "telemetry" / "2026-08-20.jsonl").write_text("{}")
    (tmp_path / "metrics" / "2026-08-20.jsonl").write_text("{}")
    status = retention_status(tmp_path, retention=LogRetention(telemetry_days=7, metrics_days=7))
    assert status["telemetry"]["files"] == 1
    assert status["metrics"]["files"] == 1
    assert status["telemetry"]["fresh"] is True


def test_retention_status_empty_logs_dir(tmp_path: Path) -> None:
    status = retention_status(tmp_path)
    assert status["telemetry"]["files"] == 0
    assert status["metrics"]["files"] == 0


def test_walk_sizes(tmp_path: Path) -> None:
    (tmp_path / "big").mkdir()
    (tmp_path / "small").mkdir()
    (tmp_path / "big" / "f").write_text("x" * 1000)
    (tmp_path / "small" / "f").write_text("x" * 10)
    entries = walk_sizes(tmp_path)
    assert len(entries) == 2
    assert entries[0]["path"].endswith("big")
    assert entries[0]["bytes"] >= 1000

"""Log↔trace correlation — JSONL log records inside a span carry trace ids."""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path

import pytest

from lumen.shared._util.logging import LoggingConfig


@pytest.fixture(autouse=True)
def _clean_logging_handlers():
    configure_module = importlib.import_module("lumen.shared._util.logging.configure")
    configure_module._remove_managed_handlers(logging.getLogger())
    yield
    configure_module._remove_managed_handlers(logging.getLogger())


def _flush_root_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_jsonl_log_entries_carry_trace_correlation(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("lumen.shared._util.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="INFO",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=1024 * 1024,
            backup_count=1,
        ),
    )
    configure_module.configure_logging(force=True)

    from lumen.shared._util.observability import (
        NoopBackend,
        begin_span,
        finish_span,
        new_trace_id,
        set_backend,
    )

    set_backend(NoopBackend())
    logger = logging.getLogger("lumen.tests.correlation")

    span, token = begin_span(
        "turn",
        kind="turn",
        trace_id=new_trace_id(),
        bind={"turn_id": "turn-abc", "session_id": "session-1"},
    )
    try:
        logger.info("inside turn")
    finally:
        finish_span(span, token)

    _flush_root_handlers()
    lines = (tmp_path / "lumen.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    assert entry["message"] == "inside turn"
    assert entry["context"]["trace_id"] == span.trace_id
    assert entry["context"]["span_id"] == span.span_id
    assert entry["context"]["turn_id"] == "turn-abc"
    assert entry["context"]["session_id"] == "session-1"


def test_log_outside_span_has_no_trace_fields(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("lumen.shared._util.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="INFO",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=1024 * 1024,
            backup_count=1,
        ),
    )
    configure_module.configure_logging(force=True)

    logger = logging.getLogger("lumen.tests.correlation.plain")
    logger.info("no span")
    _flush_root_handlers()
    lines = (tmp_path / "lumen.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    assert "trace_id" not in entry["context"]
    assert "span_id" not in entry["context"]

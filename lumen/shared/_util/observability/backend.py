"""Telemetry backend abstraction.

Business modules only see the stable contract in ``__init__``; the active
backend is a process-global chosen at startup. Default is :class:`NoopBackend`
so an unconfigured process never writes files. Production entry points call
:func:`configure` to install the local JSONL backend. All recording is
best-effort — telemetry must never break the producing code path.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import threading
import time

from .redact import sanitize_attrs
from .span import Span

logger = logging.getLogger(__name__)

__all__ = [
    "TelemetryBackend",
    "NoopBackend",
    "LocalBackend",
    "get_backend",
    "configure",
    "set_backend",
]

#: Default retention for telemetry span files (days).
DEFAULT_TELEMETRY_RETENTION_DAYS = 7


class TelemetryBackend:
    """Protocol for telemetry sinks."""

    def record_span(self, span: Span) -> None:  # pragma: no cover - protocol
        ...


class NoopBackend(TelemetryBackend):
    """Drop every record. Used by default and in automated tests."""

    def record_span(self, span: Span) -> None:
        return None


class LocalBackend(TelemetryBackend):
    """Append spans to daily JSONL files under ``<logs>/telemetry/``.

    Retention: files older than ``retention_days`` are pruned once per day.
    Attribute values are sanitized before serialization.
    """

    def __init__(
        self,
        logs_dir: str | Path | None = None,
        retention_days: int = DEFAULT_TELEMETRY_RETENTION_DAYS,
    ) -> None:
        self._logs_dir: str | Path | None = logs_dir
        self._retention_days = max(1, int(retention_days))
        self._lock = threading.Lock()
        self._prune_date: date | None = None

    def _resolve_dir(self) -> Path | None:
        if self._logs_dir is not None:
            return Path(self._logs_dir)
        try:
            from lumen.shared._util.path_service import get_path_service

            return get_path_service().get_logs_dir() / "telemetry"
        except Exception:  # pragma: no cover - environment dependent
            return None

    def _prune_if_due(self, base: Path) -> None:
        today = date.today()
        if self._prune_date == today:
            return
        with self._lock:
            if self._prune_date == today:
                return
            self._prune_date = today
            cutoff = time.time() - self._retention_days * 86400
            try:
                for path in base.glob("*.jsonl"):
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
            except OSError:
                pass

    def record_span(self, span: Span) -> None:
        base = self._resolve_dir()
        if base is None:
            return
        try:
            base.mkdir(parents=True, exist_ok=True)
            self._prune_if_due(base)
            safe_attrs = sanitize_attrs(span.attrs)
            payload = {
                "name": span.name,
                "kind": span.kind,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "started_at": span.started_at,
                "duration": span.duration,
                "call_id": span.call_id,
                "attrs": safe_attrs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            line = json.dumps(payload, ensure_ascii=False, default=str)
            path = base / f"{date.today().isoformat()}.jsonl"
            with self._lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.write("\n")
        except Exception:
            logger.debug("telemetry span record failed", exc_info=True)


_BACKEND: TelemetryBackend = NoopBackend()


def get_backend() -> TelemetryBackend:
    """Return the active telemetry backend (never raises)."""
    return _BACKEND


def set_backend(backend: TelemetryBackend | None) -> None:
    """Replace the active backend (used by tests and configuration)."""
    global _BACKEND
    _BACKEND = backend if backend is not None else NoopBackend()


def configure(
    *,
    enabled: bool = True,
    logs_dir: str | Path | None = None,
    retention_days: int = DEFAULT_TELEMETRY_RETENTION_DAYS,
) -> None:
    """Install the production local backend (or no-op when disabled).

    Call once at process entry, alongside :func:`configure_logging`.
    """
    if not enabled:
        set_backend(NoopBackend())
        return
    set_backend(LocalBackend(logs_dir=logs_dir, retention_days=retention_days))

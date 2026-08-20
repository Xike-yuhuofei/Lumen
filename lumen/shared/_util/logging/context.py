"""Request-scoped logging context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import contextvars
from typing import Any

LOG_CONTEXT_FIELDS = (
    "request_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "turn_id",
    "session_id",
    "task_id",
    "capability",
    "stage",
    "sink",
)

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "lumen_log_context", default={}
)


def current_log_context() -> dict[str, Any]:
    """Return a copy of the active logging context."""
    return dict(_context.get())


def set_log_context(**fields: Any) -> contextvars.Token[dict[str, Any]]:
    """Merge *fields* into the active logging context, returning a restore token.

    Unlike :func:`bind_log_context` this is not a context manager: the caller
    must restore the returned token later (see :func:`restore_log_context`).
    Used by the observability span machinery so a span can pin
    ``trace_id/span_id/…`` for every log record emitted inside it.
    """
    clean_fields = {key: value for key, value in fields.items() if value is not None}
    return _context.set({**_context.get(), **clean_fields})


def restore_log_context(token: contextvars.Token[dict[str, Any]]) -> None:
    """Restore the logging context captured by :func:`set_log_context`."""
    _context.reset(token)


@contextmanager
def bind_log_context(**fields: Any) -> Iterator[dict[str, Any]]:
    """Temporarily bind structured fields to all log records in this context."""
    token = set_log_context(**fields)
    try:
        yield current_log_context()
    finally:
        restore_log_context(token)

"""Redaction helpers for telemetry payloads.

Every record that leaves the observability sink passes through
:func:`sanitize_attrs` so secret-looking values (API keys, tokens,
passwords, bearer credentials) never reach the log/telemetry files.
Sanitization is intentionally conservative: unknown-but-suspicious keys are
masked too, and the whole pipeline is local-first.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["REDACTED", "redact_value", "sanitize_attrs", "sanitize_text"]

REDACTED = "[REDACTED]"

#: Attribute keys whose values are always masked (case-insensitive match on
#: the last path segment of the key).
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "x-api-key",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "authorization",
        "proxy_auth",
    }
)

#: Known high-entropy secret shapes (OpenAI-style ``sk-…``, bearer tokens,
#: and ``key=value`` inline credentials).
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-~+/=]{8,}\b", re.IGNORECASE),
    re.compile(
        r"(?i)(api[_-]?key|token|secret|passwd|password)\s*[:=]\s*[^\s,;]+"
    ),
)

_KEYS_CACHE: dict[str, bool] = {}


def _is_sensitive_key(key: str) -> bool:
    segment = str(key).strip().lower()
    cached = _KEYS_CACHE.get(segment)
    if cached is not None:
        return cached
    result = any(s in segment for s in _SENSITIVE_KEYS)
    _KEYS_CACHE[segment] = result
    return result


def redact_value(value: Any) -> Any:
    """Return *value* with known secret shapes masked (str/scalars only)."""
    if isinstance(value, str):
        masked = value
        for pattern in _SECRET_PATTERNS:
            masked = pattern.sub(REDACTED, masked)
        return masked
    return value


def sanitize_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively sanitize a telemetry attribute dict before it is recorded.

    Values under sensitive keys are fully masked; string values elsewhere are
    run through :func:`redact_value` to strip embedded secrets. Numeric values
    under token-looking keys (``prompt_tokens``, ``completion_tokens``,
    ``llm.token_count.*``) are *not* masked: credentials are strings, while
    numeric values are LLM usage metrics that observability must retain.
    """
    if not attrs:
        return dict(attrs or {})
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if _is_sensitive_key(key) and not isinstance(value, (int, float, bool)):
            out[key] = REDACTED
        elif isinstance(value, dict):
            out[key] = sanitize_attrs(value)
        elif isinstance(value, (list, tuple)):
            out[key] = [_redact_item(item) for item in value]
        else:
            out[key] = redact_value(value)
    return out


def _redact_item(item: Any) -> Any:
    if isinstance(item, dict):
        return sanitize_attrs(item)
    if isinstance(item, (list, tuple)):
        return [_redact_item(sub) for sub in item]
    return redact_value(item)


def sanitize_text(text: str | None) -> str:
    """Mask secret shapes inside a free-text string (e.g. truncated prompts)."""
    if not text:
        return text or ""
    return redact_value(text)

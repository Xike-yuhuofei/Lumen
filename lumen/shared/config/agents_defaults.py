"""Default agent (capabilities / tools / services) settings.

Canonical home of ``DEFAULT_AGENTS_SETTINGS``, migrated from
``deeptutor.services.setup.init``.
"""

from __future__ import annotations

DEFAULT_AGENTS_SETTINGS = {
    "capabilities": {
        "question": {"temperature": 0.7, "max_tokens": 4096},
        "chat": {
            "temperature": 0.2,
            "responding": {"max_tokens": 8000},
        },
    },
    "tools": {
        "brainstorm": {"temperature": 0.8, "max_tokens": 2048},
    },
    "services": {
        "personalization": {"temperature": 0.5, "max_tokens": 8192},
    },
}

__all__ = ["DEFAULT_AGENTS_SETTINGS"]

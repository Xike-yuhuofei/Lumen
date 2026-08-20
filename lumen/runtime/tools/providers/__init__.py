"""External tool providers: the tools a deployment or a user plugs in.

An *external provider* is something that contributes tools Lumen did not
ship — an MCP server today, an installed CLI app next. What they share is the
disclosure pipeline, which already exists and is source-agnostic: one manifest
line per tool in the system prompt, full schemas only after the model calls
``load_tools`` (see ``lumen.runtime.tools.deferred_tools``). What they do
*not* share is authorisation, so that stays per-kind and explicit in
:mod:`~lumen.runtime.tools.providers.authorize`.

Canonical home: ``lumen/runtime/tools/providers`` (migrated from
``lumen/runtime/providers``).  ``lumen.runtime.providers`` re-exports
these for existing importers and tests only.

Layering — this package sits **below** the tool registry:

* :mod:`allowlist` — allowed-name set with an explicit *unrestricted* state;
* :mod:`scope` — the per-turn policy inputs;
* :mod:`authorize` — one authorisation function per provider kind;
* :mod:`text` — sanitiser for provider-supplied prompt text.

Those four have no dependencies of their own, which is what lets the registry
import them (``deferred_tools`` sanitises through :mod:`text`).

:mod:`view` composes the registry, so it lives with the registry (still under
``lumen`` until the tool implementations are canonicalized).
"""

from __future__ import annotations

from lumen.runtime.tools.providers.allowlist import Allowlist
from lumen.runtime.tools.providers.authorize import authorize_mcp_tools
from lumen.runtime.tools.providers.scope import ToolScope
from lumen.runtime.tools.providers.text import (
    DOCUMENT_MAX_CHARS,
    MANIFEST_DESCRIPTION_MAX_CHARS,
    sanitize_provider_document,
    sanitize_provider_text,
)

__all__ = [
    "DOCUMENT_MAX_CHARS",
    "MANIFEST_DESCRIPTION_MAX_CHARS",
    "Allowlist",
    "ToolScope",
    "authorize_mcp_tools",
    "sanitize_provider_document",
    "sanitize_provider_text",
]

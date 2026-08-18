"""Assemble one turn's external-provider tool surface.

This is the composition seam that used to live inline in the chat pipeline:
start the providers, work out what this caller may use, filter the pool,
build the progressive-disclosure loader, and render the manifest block. It
lives here so the policy is testable on its own and so a second consumer (or
a second provider kind) does not mean a second copy inside a pipeline.

Contract: :func:`build_tool_view` **never raises**. A provider that is down,
misconfigured, or slow degrades to "no external tools this turn" — the turn
itself must still run.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolLookup
from deeptutor.runtime.registry.deferred_tools import (
    DeferredToolLoader,
    provider_identity,
    render_deferred_tools_manifest,
)
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry
from lumen.runtime.tools.providers.allowlist import Allowlist
from lumen.runtime.tools.providers.authorize import authorize_mcp_tools
from lumen.runtime.tools.providers.scope import ToolScope

logger = logging.getLogger(__name__)

#: Ceiling on connecting a caller's own servers. This runs before the turn's
#: first stream event, so it is the one place a slow third-party host could
#: present as "DeepTutor hung".
_OWNER_SCOPE_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class ProviderToolView:
    """One turn's resolved provider surface."""

    #: Registry the turn should use for lookup and dispatch (scoped view).
    registry: ToolLookup
    #: ``None`` when this turn has no external tools at all.
    loader: DeferredToolLoader | None
    #: Provider tools visible this turn — the manifest's contents, and what
    #: the context-budget chip counts as "unloaded extended tools".
    pool: tuple[BaseTool, ...]
    #: Rendered ``extended_tools`` system-prompt block ("" when suppressed).
    manifest: str

    @classmethod
    def empty(cls, registry: ToolLookup) -> "ProviderToolView":
        return cls(registry=registry, loader=None, pool=(), manifest="")

    def attach(self, tool_schemas: list[dict[str, Any]]) -> None:
        """Add already-loaded schemas and bind the turn's live schema list.

        The loader appends to this list as the model calls ``load_tools``, and
        the agent loop re-reads it every round, so tools become callable
        without rebuilding the request.
        """
        if self.loader is None:
            return
        tool_schemas.extend(self.loader.initial_schemas())
        self.loader.bind_live_schemas(tool_schemas)


async def build_tool_view(
    *,
    base_registry: ToolLookup,
    scope: ToolScope,
    language: str = "en",
    refusal_message: str = "",
) -> ProviderToolView:
    """Resolve the provider tools *scope* may use this turn."""
    try:
        return await _build(
            base_registry=base_registry,
            scope=scope,
            language=language,
            refusal_message=refusal_message,
        )
    except Exception:
        logger.warning("provider tool view assembly failed; continuing without", exc_info=True)
        return ProviderToolView.empty(base_registry)


async def _build(
    *,
    base_registry: ToolLookup,
    scope: ToolScope,
    language: str,
    refusal_message: str,
) -> ProviderToolView:
    shared_pool = list(base_registry.deferred_tools())
    owned_pool: list[BaseTool] = []
    if not shared_pool and not owned_pool:
        return ProviderToolView.empty(base_registry)

    implicit_names = {
        tool.get_definition().name
        for tool in shared_pool
        if provider_identity(tool)[1] in scope.implicit_provider_ids
    }

    allowed = authorize_mcp_tools(
        scope=scope,
        user_grant=_user_grant(scope),
        implicit_names=implicit_names,
        owned_names=[tool.get_definition().name for tool in owned_pool],
    )

    pool = tuple(
        tool for tool in (*shared_pool, *owned_pool) if allowed.allows(tool.get_definition().name)
    )
    registry = ScopedToolRegistry(
        base=base_registry,
        overlay=[*owned_pool],
        allowed=allowed,
        refusal_message=refusal_message,
    )
    if not pool:
        return ProviderToolView(registry=registry, loader=None, pool=(), manifest="")

    loader = DeferredToolLoader(
        registry=registry,
        session_id=scope.session_id,
        loaded=implicit_names,
        allowed=allowed.as_set(),
    )
    manifest = (
        ""
        if scope.exclusive_capability
        else render_deferred_tools_manifest(list(pool), language=language)
    )
    return ProviderToolView(registry=registry, loader=loader, pool=pool, manifest=manifest)


def _user_grant(scope: ToolScope) -> Allowlist:
    """The caller's ``grant.mcp_tools``, or unrestricted for a partner turn.

    A partner has no account and therefore no grant; its surface is decided by
    the partner's own configured whitelist, which reaches us as
    ``scope.caller_whitelist``.
    """
    if scope.is_partner:
        return Allowlist.unrestricted()
    from lumen.shared._util.user import allowed_mcp_tools

    return Allowlist.of(allowed_mcp_tools())


__all__ = ["ProviderToolView", "build_tool_view"]

"""Production bootstrap — the single formal dependency-assembly entry.

Since Phase 5 the Lumen application is assembled through the Plugin Kernel:

    load profile → Plugin Bootstrap → Runtime + Shared + mode.learn

The legacy lumen startup paths are retained only as a compatibility /
rollback path (deprecated), never as a second formal lifecycle.
"""

from __future__ import annotations

import os
from typing import Any

from lumen.kernel import Bootstrap, PluginContext
from lumen.profile import PRODUCTION_PLUGINS, PRODUCTION_PROFILE

#: Env var that elects the dev Active Provider for ``runtime.agent_loop``.
#: ``langgraph_thin`` = P1 (dev default); ``legacy`` / unset = P0 (production
#: default, unchanged).
AGENT_LOOP_PROVIDER_ENV = "LUMEN_AGENT_LOOP_PROVIDER"


def resolve_active_assembly() -> tuple[Any, list[Any]]:
    """Return ``(profile, plugins)`` for the process's Active Provider.

    Production default (env unset or ``legacy``) = ``PRODUCTION_PROFILE``
    (P0 / Legacy — unchanged).  Dev selects P1 (``langgraph_thin``) via the
    env var; P0 fast-fallback is one env change away.
    """
    provider = os.environ.get(AGENT_LOOP_PROVIDER_ENV, "").strip().lower()
    if provider == "langgraph_thin":
        from lumen.dev_profile import DEV_PLUGINS, DEV_PROFILE

        return DEV_PROFILE, list(DEV_PLUGINS)
    return PRODUCTION_PROFILE, list(PRODUCTION_PLUGINS)


class LumenBootstrap:
    """Owns one Plugin Kernel assembly and its shutdown lifecycle.

    ``boot()`` returns the root :class:`PluginContext`; ``shutdown()`` awaits
    ``root.dispose()``, releasing every service registration, background task
    and registered cleanup.  Idempotent and safe to call once.
    """

    def __init__(
        self,
        profile: Any | None = None,
        plugins: list[Any] | None = None,
    ) -> None:
        if profile is None or plugins is None:
            resolved_profile, resolved_plugins = resolve_active_assembly()
            profile = profile if profile is not None else resolved_profile
            plugins = plugins if plugins is not None else resolved_plugins
        self._profile = profile
        self._plugins = plugins
        self._root: PluginContext | None = None

    async def boot(self) -> PluginContext:
        """Assemble the runtime.  Raises on any dependency/validation error
        before any service is exposed."""
        if self._root is not None:
            return self._root
        bootstrap = Bootstrap(profile=self._profile)
        self._root = await bootstrap.boot(self._plugins)
        return self._root

    async def shutdown(self) -> None:
        """Dispose the whole assembly (idempotent)."""
        if self._root is None:
            return
        await self._root.dispose()
        self._root = None

    @property
    def root(self) -> PluginContext | None:
        return self._root

    def resolve_mode(self, capability: str | None) -> str:
        """Map an external capability request onto a kernel mode.

        The only Learn product abstraction is ``mode.learn``; legacy names
        (``mastery_path`` / ``mastery``) are accepted as compatibility entries
        and rewritten through :func:`lumen.compat.resolve_learn_mode`. This is
        the entry-layer mapping for the new bootstrap — the legacy mastery
        path remains only as a rollback route.
        """
        from lumen.compat import resolve_learn_mode

        return resolve_learn_mode(capability) or (capability or "chat")

    def learn_service(self, capability: str | None = None):
        """Resolve the kernel's ``mode.learn`` service for a learn request.

        Accepts the canonical ``mode.learn`` plus the legacy ``mastery_path``
        / ``mastery`` compatibility names.  Returns ``None`` when the kernel
        is not booted or the request is not a learn mode.
        """
        if self._root is None:
            return None
        mode = self.resolve_mode(capability)
        if mode != "mode.learn":
            return None
        return self._root.optional("mode.learn")

    def agent_loop_service(self):
        """Resolve the kernel's ``runtime.agent_loop`` service (the unified
        Runtime entry for a generic agent turn).

        Returns ``None`` when the kernel is not booted, so callers can fall
        back to the deprecated legacy orchestrator assembly.
        """
        if self._root is None:
            return None
        return self._root.optional("runtime.agent_loop")


async def boot_lumen(
    profile: Any | None = None,
    plugins: list[Any] | None = None,
) -> PluginContext:
    """One-shot convenience: boot the production runtime and return its root."""
    return await LumenBootstrap(profile=profile, plugins=plugins).boot()


# ── Active-assembly bridge ─────────────────────────────────────────────────
#
# The process-level handle to the booted Plugin Kernel.  The FastAPI
# lifespan attaches the booted assembly on startup and detaches on
# shutdown; every other entry (CLI / SDK / Cron) resolves services lazily
# and the first resolution boots the production assembly on demand — so
# ALL entries converge on the same Runtime contracts.  This is NOT a
# service locator for internal dependencies — plugins resolve services via
# constructor injection inside the kernel; this only hands the transport /
# app layer a reference to the one booted assembly.

_active_bootstrap: LumenBootstrap | None = None


def attach_bootstrap(bootstrap: LumenBootstrap) -> None:
    """Register the booted assembly as the active one (FastAPI lifespan)."""
    global _active_bootstrap
    _active_bootstrap = bootstrap


def get_active_bootstrap() -> LumenBootstrap | None:
    """Return the active booted assembly, or ``None`` if not booted."""
    return _active_bootstrap


def detach_bootstrap() -> None:
    """Clear the active assembly reference (FastAPI shutdown)."""
    global _active_bootstrap
    _active_bootstrap = None


async def ensure_active_bootstrap() -> LumenBootstrap:
    """Return the active assembly, booting the production profile on demand.

    Idempotent: once an assembly is attached it is reused.  On an unlikely
    concurrent first-boot race the losing candidate is disposed and the
    winner is returned.  Boot errors propagate — without the Plugin Kernel
    there is no runtime, so callers fail the turn with a clear error
    instead of silently falling back to a deprecated assembly.
    """
    global _active_bootstrap
    bootstrap = _active_bootstrap
    if bootstrap is not None:
        return bootstrap
    candidate = LumenBootstrap()
    await candidate.boot()
    if _active_bootstrap is None:
        _active_bootstrap = candidate
        return candidate
    await candidate.shutdown()
    return _active_bootstrap


async def resolve_learn_service(capability: str | None = None):
    """Resolve ``mode.learn`` for a Learn request (``mastery_path`` /
    ``mastery`` / ``mode.learn``) from the active assembly.

    Returns ``None`` when the request is not a Learn mode.  Otherwise the
    production assembly is booted on demand if no assembly is active yet.
    """
    from lumen.compat import resolve_learn_mode

    if resolve_learn_mode(capability) != "mode.learn":
        return None
    bootstrap = _active_bootstrap
    if bootstrap is None:
        bootstrap = await ensure_active_bootstrap()
    return bootstrap.learn_service(capability)


async def resolve_agent_loop_service():
    """Resolve ``runtime.agent_loop`` — the unified Runtime entry for a
    generic agent turn (WS / CLI / Cron / SDK) — from the active assembly.

    The production assembly is booted on demand if no assembly is active
    yet, so every generic turn runs through the same Runtime contract.
    """
    bootstrap = _active_bootstrap
    if bootstrap is None:
        bootstrap = await ensure_active_bootstrap()
    return bootstrap.agent_loop_service()

"""Kernel bootstrap orchestration."""

from __future__ import annotations

from lumen.kernel.context import PluginContext
from lumen.kernel.plugin import Plugin
from lumen.kernel.profile import Profile
from lumen.kernel.resolver import DependencyResolver


class Bootstrap:
    """Validate, order, and start plugins on a fresh root context.

    Each plugin receives a shared child context: services land in one flat
    namespace while undo callbacks stay scoped per plugin. Any setup failure
    awaits ``root.dispose()`` — cascading through every plugin context in
    reverse start order and awaiting every async cleanup — before
    re-raising, so rollback is complete when the error surfaces.
    """

    def __init__(
        self,
        resolver: DependencyResolver | None = None,
        profile: Profile | None = None,
    ) -> None:
        self._resolver = resolver or DependencyResolver()
        self._profile = profile or Profile()

    async def boot(self, plugins: list[Plugin]) -> PluginContext:
        manifests = [plugin.manifest for plugin in plugins]
        selected = self._profile.select(manifests)
        ordered = self._resolver.resolve(selected, bindings=self._profile.bindings)
        plugin_by_id = {plugin.manifest.id: plugin for plugin in plugins}
        root = PluginContext()
        try:
            for manifest in ordered:
                await plugin_by_id[manifest.id].setup(root.child(shared=True))
        except BaseException:
            await root.dispose()
            raise
        return root

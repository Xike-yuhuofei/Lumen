"""Profile selection: which plugins boot and which provider wins a service."""

from __future__ import annotations

from dataclasses import dataclass, field

from lumen.kernel.plugin import PluginManifest


@dataclass(slots=True)
class Profile:
    """Compose a runtime from plugins and service-provider bindings.

    ``manifests`` is a plugin-id whitelist (empty = all candidates boot).
    ``bindings`` maps service name -> provider plugin id; when several
    plugins provide the same service, the binding elects the winner and
    the losing providers are not activated.
    """

    manifests: list[PluginManifest] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)

    def select(self, manifests: list[PluginManifest]) -> list[PluginManifest]:
        if not self.manifests:
            return list(manifests)
        allowed = {manifest.id for manifest in self.manifests}
        return [manifest for manifest in manifests if manifest.id in allowed]

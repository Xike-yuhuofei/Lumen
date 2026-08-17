"""Dependency validation and provider election for plugin manifests."""

from __future__ import annotations

from collections import defaultdict, deque

from lumen.kernel.plugin import PluginManifest


class DependencyResolver:
    """Validate and order plugin manifests before anything is started.

    ``bindings`` (service name -> provider plugin id, typically taken from
    the Profile) resolves services declared by several plugins: the bound
    provider is elected and the competing providers are not activated at
    all. Every check below runs up front, in this order:

    1. duplicate plugin ids
    2. invalid bindings (unknown plugin, or plugin does not provide the service)
    3. ambiguous services (several providers, no binding)
    4. binding conflicts (a bound provider loses another bound service)
    5. missing required dependencies (against the post-election provider set)
    6. dependency cycles (Kahn's algorithm over the activated set)

    The returned order is deterministic: Kahn's queue is seeded and drained
    in sorted plugin-id order.
    """

    def resolve(
        self,
        manifests: list[PluginManifest],
        bindings: dict[str, str] | None = None,
    ) -> list[PluginManifest]:
        bindings = dict(bindings or {})
        ids = [manifest.id for manifest in manifests]
        duplicate_ids = sorted({plugin_id for plugin_id in ids if ids.count(plugin_id) > 1})
        if duplicate_ids:
            raise RuntimeError(f"duplicate plugin id: {', '.join(duplicate_ids)}")

        by_id = {manifest.id: manifest for manifest in manifests}
        for service, provider_id in sorted(bindings.items()):
            provider = by_id.get(provider_id)
            if provider is None:
                raise RuntimeError(
                    f"binding for service '{service}' references unknown plugin: {provider_id}"
                )
            if service not in provider.provides:
                raise RuntimeError(
                    f"binding for service '{service}' targets plugin '{provider_id}', "
                    "which does not provide it"
                )

        providers: dict[str, list[PluginManifest]] = defaultdict(list)
        for manifest in manifests:
            for service in manifest.provides:
                providers[service].append(manifest)

        shadowed: set[str] = set()
        for service in sorted(providers):
            registered = providers[service]
            if len(registered) == 1:
                continue
            bound = bindings.get(service)
            if bound is None:
                candidate_ids = ", ".join(sorted(manifest.id for manifest in registered))
                raise RuntimeError(
                    f"duplicate provider for service '{service}': {candidate_ids} "
                    "(no profile binding elects one)"
                )
            shadowed.update(manifest.id for manifest in registered if manifest.id != bound)

        conflicting = sorted({pid for pid in bindings.values() if pid in shadowed})
        if conflicting:
            raise RuntimeError(
                f"binding conflict: bound provider {', '.join(conflicting)} is shadowed "
                "by another binding and would not activate"
            )

        active = [manifest for manifest in manifests if manifest.id not in shadowed]

        # Effective provider set: services of non-activated plugins vanish with
        # them, so dependents get a deterministic missing-dependency error
        # instead of a runtime LookupError.
        elected: dict[str, str] = {}
        for manifest in active:
            for service in manifest.provides:
                elected[service] = manifest.id
        for manifest in active:
            missing = [name for name in manifest.requires if name not in elected]
            if missing:
                raise RuntimeError(
                    f"missing dependency for {manifest.id}: {', '.join(sorted(missing))}"
                )

        active_ids = {manifest.id for manifest in active}
        graph: dict[str, set[str]] = {plugin_id: set() for plugin_id in active_ids}
        indegree: dict[str, int] = {plugin_id: 0 for plugin_id in active_ids}
        for manifest in active:
            for dep in set(manifest.requires):
                owner = elected[dep]
                if owner != manifest.id:
                    graph[owner].add(manifest.id)
                    indegree[manifest.id] += 1

        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        ordered_ids: list[str] = []
        while queue:
            node = queue.popleft()
            ordered_ids.append(node)
            for child in sorted(graph[node]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(ordered_ids) != len(active):
            raise RuntimeError("dependency cycle detected")

        return [by_id[plugin_id] for plugin_id in ordered_ids]

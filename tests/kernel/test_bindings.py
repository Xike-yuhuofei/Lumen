"""Tests for Profile provider bindings (Phase 1.5)."""

from __future__ import annotations

import pytest

from lumen.kernel import (
    Bootstrap,
    DependencyResolver,
    Plugin,
    PluginContext,
    PluginManifest,
    Profile,
)


def make_plugin(
    plugin_id: str,
    provides: list[str] | None = None,
    requires: list[str] | None = None,
    setup_impl=None,
):
    manifest = PluginManifest(
        id=plugin_id,
        provides=list(provides or []),
        requires=list(requires or []),
    )

    class _Plugin(Plugin):
        def __init__(self):
            self.manifest = manifest

        async def setup(self, ctx: PluginContext) -> None:
            if setup_impl is not None:
                await setup_impl(ctx)

    return _Plugin()


# --- Binding elects a provider -----------------------------------------------------


def test_binding_elects_provider_and_shadows_losers():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="llm.ollama", provides=["runtime.llm"]),
        PluginManifest(id="llm.openai", provides=["runtime.llm"]),
        PluginManifest(id="chat", requires=["runtime.llm"]),
    ]
    ordered = resolver.resolve(manifests, bindings={"runtime.llm": "llm.openai"})
    # the losing provider is not activated at all; consumers order after the winner
    assert [m.id for m in ordered] == ["llm.openai", "chat"]


def test_multiple_providers_without_binding_is_error():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["svc"]),
        PluginManifest(id="b", provides=["svc"]),
    ]
    with pytest.raises(
        RuntimeError, match="duplicate provider for service 'svc'.*no profile binding"
    ):
        resolver.resolve(manifests)


def test_single_provider_needs_no_binding():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["svc"]),
        PluginManifest(id="b", requires=["svc"]),
    ]
    ordered = resolver.resolve(manifests)
    assert [m.id for m in ordered] == ["a", "b"]


# --- Invalid bindings ---------------------------------------------------------------


def test_binding_to_unknown_plugin_is_error():
    resolver = DependencyResolver()
    manifests = [PluginManifest(id="a", provides=["svc"])]
    with pytest.raises(RuntimeError, match="unknown plugin: ghost"):
        resolver.resolve(manifests, bindings={"svc": "ghost"})


def test_binding_to_plugin_not_providing_service_is_error():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["x"]),
        PluginManifest(id="b", provides=["y"]),
    ]
    with pytest.raises(RuntimeError, match="targets plugin 'a', which does not provide it"):
        resolver.resolve(manifests, bindings={"y": "a"})


def test_binding_conflict_when_bound_provider_is_shadowed():
    # a provides s and t; t is bound to b, so a is shadowed — but a is bound
    # for s, which can never activate.
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["s", "t"]),
        PluginManifest(id="b", provides=["t"]),
    ]
    with pytest.raises(RuntimeError, match="binding conflict"):
        resolver.resolve(manifests, bindings={"s": "a", "t": "b"})


# --- Missing dependency / cycle still hold ------------------------------------------


def test_shadowed_providers_services_vanish():
    # b provides svc AND t; binding elects a for svc, so b is shadowed and
    # t loses its only provider -> deterministic missing-dependency error.
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["svc"]),
        PluginManifest(id="b", provides=["svc", "t"]),
        PluginManifest(id="c", requires=["t"]),
    ]
    with pytest.raises(RuntimeError, match="missing dependency for c: t"):
        resolver.resolve(manifests, bindings={"svc": "a"})


def test_cycle_detected_with_bindings():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["x"], requires=["y"]),
        PluginManifest(id="b", provides=["y"], requires=["x"]),
    ]
    with pytest.raises(RuntimeError, match="cycle"):
        resolver.resolve(manifests, bindings={"x": "a", "y": "b"})


def test_cycle_detected_alongside_bindings():
    """A cycle between free providers still errors even when an unrelated
    service is resolved via binding."""

    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["x"], requires=["z"]),
        PluginManifest(id="c", provides=["z"], requires=["x"]),
        PluginManifest(id="p1", provides=["m"]),
        PluginManifest(id="p2", provides=["m"]),
    ]
    with pytest.raises(RuntimeError, match="cycle"):
        resolver.resolve(manifests, bindings={"m": "p1"})


# --- Determinism --------------------------------------------------------------------


def test_resolution_is_deterministic_across_input_orders():
    resolver = DependencyResolver()
    base = [
        PluginManifest(id="d", requires=["c"]),
        PluginManifest(id="b", provides=["b"], requires=["a"]),
        PluginManifest(id="c", provides=["c"], requires=["b"]),
        PluginManifest(id="a", provides=["a"]),
        PluginManifest(id="e"),
    ]
    first = resolver.resolve(list(base))
    second = resolver.resolve(list(reversed(base)))
    assert [m.id for m in first] == [m.id for m in second]
    # deterministic Kahn order: sorted seed queue ['a', 'e'], then dependents
    # released in dependency order
    assert [m.id for m in first] == ["a", "e", "b", "c", "d"]


def test_bound_winner_deterministic_regardless_of_input_order():
    resolver = DependencyResolver()
    winner_first = resolver.resolve(
        [
            PluginManifest(id="p1", provides=["svc"]),
            PluginManifest(id="p2", provides=["svc"]),
            PluginManifest(id="consumer", requires=["svc"]),
        ],
        bindings={"svc": "p2"},
    )
    winner_last = resolver.resolve(
        [
            PluginManifest(id="consumer", requires=["svc"]),
            PluginManifest(id="p2", provides=["svc"]),
            PluginManifest(id="p1", provides=["svc"]),
        ],
        bindings={"svc": "p2"},
    )
    assert [m.id for m in winner_first] == [m.id for m in winner_last] == ["p2", "consumer"]


# --- Bootstrap integration -----------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_binding_activates_only_elected_provider():
    started: list[str] = []

    def starter(plugin_id: str):
        async def setup(ctx: PluginContext):
            started.append(plugin_id)
            ctx.provide("runtime.llm", plugin_id)

        return setup

    ollama = make_plugin("llm.ollama", provides=["runtime.llm"], setup_impl=starter("llm.ollama"))
    openai = make_plugin("llm.openai", provides=["runtime.llm"], setup_impl=starter("llm.openai"))

    async def consumer_setup(ctx: PluginContext):
        assert ctx.require("runtime.llm") == "llm.openai"
        started.append("chat")

    chat = make_plugin("chat", requires=["runtime.llm"], setup_impl=consumer_setup)

    profile = Profile(bindings={"runtime.llm": "llm.openai"})
    root = await Bootstrap(profile=profile).boot([ollama, openai, chat])
    assert started == ["llm.openai", "chat"]
    assert root.require("runtime.llm") == "llm.openai"
    await root.dispose()


@pytest.mark.asyncio
async def test_bootstrap_unbound_ambiguous_provider_fails_before_setup():
    started: list[str] = []

    async def setup(ctx: PluginContext):
        started.append("boom")

    a = make_plugin("a", provides=["svc"], setup_impl=setup)
    b = make_plugin("b", provides=["svc"], setup_impl=setup)

    with pytest.raises(RuntimeError, match="duplicate provider for service 'svc'"):
        await Bootstrap().boot([a, b])
    assert started == []  # nothing ran: the error fires before any setup


@pytest.mark.asyncio
async def test_bootstrap_invalid_binding_fails_before_setup():
    async def setup(ctx: PluginContext):
        raise AssertionError("must not run")

    a = make_plugin("a", provides=["svc"], setup_impl=setup)
    profile = Profile(bindings={"svc": "ghost"})
    with pytest.raises(RuntimeError, match="unknown plugin: ghost"):
        await Bootstrap(profile=profile).boot([a])

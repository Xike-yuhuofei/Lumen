"""Tests for the minimal Lumen plugin kernel (Phase 1)."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import pkgutil
import subprocess
import sys

import pytest

from lumen.kernel import (
    BackgroundTask,
    Bootstrap,
    DependencyResolver,
    DisposalStack,
    EventBus,
    Plugin,
    PluginContext,
    PluginManifest,
    Profile,
    ServiceRegistry,
)


def make_plugin(
    plugin_id: str,
    provides: list[str] | None = None,
    requires: list[str] | None = None,
    optional: list[str] | None = None,
    setup_impl=None,
):
    manifest = PluginManifest(
        id=plugin_id,
        provides=list(provides or []),
        requires=list(requires or []),
        optional=list(optional or []),
    )

    class _Plugin(Plugin):
        def __init__(self):
            self.manifest = manifest

        async def setup(self, ctx: PluginContext) -> None:
            if setup_impl is not None:
                await setup_impl(ctx)

    return _Plugin()


# --- Plugin registration / read ----------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_registers_and_reads_service():
    async def setup(ctx: PluginContext):
        ctx.provide("greeting", "hello")
        assert ctx.require("greeting") == "hello"

    plugin = make_plugin("a", provides=["greeting"], setup_impl=setup)
    root = await Bootstrap().boot([plugin])
    assert root.require("greeting") == "hello"
    await root.dispose()


@pytest.mark.asyncio
async def test_plugin_b_requires_plugin_a():
    async def a_setup(ctx: PluginContext):
        ctx.provide("svc_a", "svc_a")

    b_calls: list[str] = []

    async def b_setup(ctx: PluginContext):
        b_calls.append(ctx.require("svc_a"))

    a = make_plugin("a", provides=["svc_a"], setup_impl=a_setup)
    b = make_plugin("b", requires=["svc_a"], setup_impl=b_setup)
    root = await Bootstrap().boot([a, b])
    assert b_calls == ["svc_a"]
    await root.dispose()


# --- Dependency resolution errors --------------------------------------------------


def test_resolver_missing_dependency():
    resolver = DependencyResolver()
    manifests = [PluginManifest(id="b", requires=["missing"])]
    with pytest.raises(RuntimeError, match="missing dependency"):
        resolver.resolve(manifests)


def test_resolver_duplicate_provider():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["dup"]),
        PluginManifest(id="b", provides=["dup"]),
    ]
    with pytest.raises(RuntimeError, match="duplicate provider"):
        resolver.resolve(manifests)


def test_resolver_dependency_cycle():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="a", provides=["x"], requires=["y"]),
        PluginManifest(id="b", provides=["y"], requires=["x"]),
    ]
    with pytest.raises(RuntimeError, match="cycle"):
        resolver.resolve(manifests)


def test_resolver_orders_dependencies():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="b", provides=["b"], requires=["a"]),
        PluginManifest(id="a", provides=["a"]),
        PluginManifest(id="c", provides=["c"], requires=["b"]),
    ]
    ordered = resolver.resolve(manifests)
    assert [m.id for m in ordered] == ["a", "b", "c"]


def test_resolver_optional_dependency_missing_ok():
    resolver = DependencyResolver()
    manifests = [PluginManifest(id="a", provides=["x"], optional=["y"])]
    ordered = resolver.resolve(manifests)
    assert [m.id for m in ordered] == ["a"]


# --- Parent / child context --------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_child_context_inheritance():
    parent = PluginContext()
    parent.provide("svc", "parent_value")
    child = parent.child()
    assert child.require("svc") == "parent_value"
    await parent.dispose()


@pytest.mark.asyncio
async def test_child_context_shadows_parent():
    parent = PluginContext()
    parent.provide("svc", "parent")
    child = parent.child()
    child.provide("svc", "child")
    assert child.require("svc") == "child"
    assert parent.require("svc") == "parent"
    await parent.dispose()


@pytest.mark.asyncio
async def test_dispose_removes_registration():
    ctx = PluginContext()
    ctx.provide("svc", "value")
    assert ctx.optional("svc") == "value"
    await ctx.dispose()
    with pytest.raises(LookupError):
        ctx.require("svc")


@pytest.mark.asyncio
async def test_dispose_runs_callbacks_in_reverse():
    calls: list[str] = []
    ctx = PluginContext()
    ctx.on_dispose(lambda: calls.append("first"))
    ctx.on_dispose(lambda: calls.append("second"))
    await ctx.dispose()
    assert calls == ["second", "first"]


# --- Event bus --------------------------------------------------------------------


def test_event_bus_subscribe_and_publish():
    bus = EventBus()
    received: list[str] = []
    bus.subscribe("evt", lambda payload: received.append(payload))
    bus.publish("evt", "hello")
    assert received == ["hello"]


def test_event_bus_unsubscribe():
    bus = EventBus()
    received: list[str] = []

    def listener(payload):
        received.append(payload)

    unsubscribe = bus.subscribe("evt", listener)
    bus.publish("evt", "a")
    unsubscribe()
    bus.publish("evt", "b")
    assert received == ["a"]


@pytest.mark.asyncio
async def test_event_listener_auto_removed_on_dispose():
    bus = EventBus()
    ctx = PluginContext()
    received: list[str] = []

    def listener(payload):
        received.append(payload)

    unsubscribe = bus.subscribe("evt", listener)
    ctx.on_dispose(unsubscribe)
    bus.publish("evt", "first")
    await ctx.dispose()
    bus.publish("evt", "second")
    assert received == ["first"]


# --- Background task cancellation -------------------------------------------------


@pytest.mark.asyncio
async def test_background_task_cancelled_on_dispose():
    ctx = PluginContext()
    cancelled = asyncio.Event()

    async def long_running():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(long_running())
    ctx.track_task(task)
    await asyncio.sleep(0)  # let the coroutine start and reach its await point
    await ctx.dispose()
    # dispose awaits the cancelled task, so both hold immediately after
    assert cancelled.is_set()
    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_background_task_awaited_after_cancel():
    """dispose() waits for the task's own cleanup, not just the cancel call."""

    ctx = PluginContext()
    cleanup_done = asyncio.Event()

    async def worker():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)  # post-cancel cleanup work
            cleanup_done.set()
            raise

    task = asyncio.create_task(worker())
    ctx.track_task(task)
    await asyncio.sleep(0)
    await ctx.dispose()
    assert cleanup_done.is_set()
    assert task.done()


@pytest.mark.asyncio
async def test_disposal_stack_reverse_order():
    stack = DisposalStack()
    calls: list[str] = []
    stack.push(lambda: calls.append("a"))
    stack.push(lambda: calls.append("b"))
    await stack.dispose()
    assert calls == ["b", "a"]


@pytest.mark.asyncio
async def test_disposal_stack_mixed_sync_and_async_reverse_order():
    stack = DisposalStack()
    calls: list[str] = []

    async def async_a():
        calls.append("a")

    stack.push(async_a)
    stack.push(lambda: calls.append("b"))

    async def async_c():
        calls.append("c")

    stack.push(async_c)
    await stack.dispose()
    assert calls == ["c", "b", "a"]


@pytest.mark.asyncio
async def test_disposal_stack_awaits_async_callback():
    stack = DisposalStack()
    finished = asyncio.Event()

    async def slow_cleanup():
        await asyncio.sleep(0.01)
        finished.set()

    stack.push(slow_cleanup)
    await stack.dispose()
    assert finished.is_set()


@pytest.mark.asyncio
async def test_disposal_stack_continues_after_failing_callback():
    stack = DisposalStack()
    calls: list[str] = []

    def boom():
        raise ValueError("cleanup failed")

    stack.push(lambda: calls.append("first"))
    stack.push(boom)
    stack.push(lambda: calls.append("last"))
    await stack.dispose()
    assert calls == ["last", "first"]


@pytest.mark.asyncio
async def test_disposal_stack_idempotent():
    stack = DisposalStack()
    calls: list[str] = []
    stack.push(lambda: calls.append("once"))
    await stack.dispose()
    await stack.dispose()
    assert calls == ["once"]
    assert stack.disposed


@pytest.mark.asyncio
async def test_disposal_stack_rejects_after_dispose():
    stack = DisposalStack()
    await stack.dispose()
    with pytest.raises(RuntimeError):
        stack.push(lambda: None)


# --- Setup failure rollback -------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_failure_rolls_back():
    rolled_back: list[str] = []

    async def a_setup(ctx: PluginContext):
        ctx.provide("svc_a", "a")
        ctx.on_dispose(lambda: rolled_back.append("a"))

    async def b_setup(ctx: PluginContext):
        raise RuntimeError("boom")

    a = make_plugin("a", provides=["svc_a"], setup_impl=a_setup)
    b = make_plugin("b", requires=["svc_a"], setup_impl=b_setup)

    with pytest.raises(RuntimeError, match="boom"):
        await Bootstrap().boot([a, b])

    assert rolled_back == ["a"]


@pytest.mark.asyncio
async def test_setup_failure_after_partial_registration():
    async def a_setup(ctx: PluginContext):
        ctx.provide("svc_a", "a")

    async def b_setup(ctx: PluginContext):
        ctx.provide("svc_b", "b")
        raise RuntimeError("fail")

    a = make_plugin("a", provides=["svc_a"], setup_impl=a_setup)
    b = make_plugin("b", provides=["svc_b"], requires=["svc_a"], setup_impl=b_setup)

    with pytest.raises(RuntimeError):
        await Bootstrap().boot([a, b])


@pytest.mark.asyncio
async def test_setup_failure_rollback_awaits_async_cleanup():
    """Rollback awaits async cleanup before the boot error surfaces."""

    cleaned = asyncio.Event()
    closed_services: list[str] = []

    async def a_setup(ctx: PluginContext):
        ctx.provide("svc_a", "a")

        async def async_close():
            await asyncio.sleep(0.01)
            closed_services.append("svc_a")
            cleaned.set()

        ctx.on_dispose(async_close)

    async def b_setup(ctx: PluginContext):
        raise RuntimeError("boom")

    a = make_plugin("a", provides=["svc_a"], setup_impl=a_setup)
    b = make_plugin("b", requires=["svc_a"], setup_impl=b_setup)

    with pytest.raises(RuntimeError, match="boom"):
        await Bootstrap().boot([a, b])

    assert cleaned.is_set()
    assert closed_services == ["svc_a"]


@pytest.mark.asyncio
async def test_context_dispose_cascades_to_children():
    order: list[str] = []

    parent = PluginContext()
    child = parent.child()
    grandchild = child.child()

    def teardown(where: str):
        order.append(where)

    parent.on_dispose(lambda: teardown("parent"))
    child.on_dispose(lambda: teardown("child"))
    grandchild.on_dispose(lambda: teardown("grandchild"))

    await parent.dispose()
    # children first, most dependent first, then the parent itself
    assert order == ["grandchild", "child", "parent"]


# --- ServiceRegistry --------------------------------------------------------------


def test_service_registry_duplicate_provider():
    reg = ServiceRegistry()
    reg.provide("svc", 1)
    with pytest.raises(RuntimeError):
        reg.provide("svc", 2)


def test_service_registry_require_missing():
    reg = ServiceRegistry()
    with pytest.raises(LookupError):
        reg.require("missing")


# --- Profile -----------------------------------------------------------------------


def test_profile_filters_plugins():
    manifests = [
        PluginManifest(id="a", provides=["x"]),
        PluginManifest(id="b", provides=["y"]),
    ]
    profile = Profile(manifests=[manifests[0]])
    selected = profile.select(manifests)
    assert [m.id for m in selected] == ["a"]


def test_profile_empty_selects_all():
    manifests = [
        PluginManifest(id="a"),
        PluginManifest(id="b"),
    ]
    profile = Profile()
    selected = profile.select(manifests)
    assert len(selected) == 2


# --- Kernel isolation -------------------------------------------------------------


_FORBIDDEN_DOMAINS = [
    "llm",
    "rag",
    "memory",
    "learn",
    "teaching",
    "news",
    "review",
    "agent",
]


def test_kernel_does_not_import_domain_modules():
    import lumen.kernel

    for _finder, name, _is_pkg in pkgutil.iter_modules(lumen.kernel.__path__):
        module = importlib.import_module(f"lumen.kernel.{name}")
        source_file = getattr(module, "__file__", "")
        if not source_file:
            continue
        with open(source_file) as f:
            source = f.read().lower()
        for domain in _FORBIDDEN_DOMAINS:
            assert domain not in source, (
                f"lumen.kernel.{name} references forbidden domain '{domain}'"
            )


def test_kernel_isolation_in_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "import lumen.kernel; print('ok')"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# --- Bootstrap with profile -------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_with_profile_selects_subset():
    async def a_setup(ctx: PluginContext):
        ctx.provide("svc_a", "a")

    async def b_setup(ctx: PluginContext):
        ctx.provide("svc_b", "b")

    a = make_plugin("a", provides=["svc_a"], setup_impl=a_setup)
    b = make_plugin("b", provides=["svc_b"], setup_impl=b_setup)

    profile = Profile(manifests=[PluginManifest(id="a", provides=["svc_a"])])
    root = await Bootstrap(profile=profile).boot([a, b])
    assert root.optional("svc_a") == "a"
    assert root.optional("svc_b") is None
    await root.dispose()


# --- Context disposed guards ------------------------------------------------------


@pytest.mark.asyncio
async def test_context_rejects_provide_after_dispose():
    ctx = PluginContext()
    await ctx.dispose()
    with pytest.raises(RuntimeError):
        ctx.provide("svc", 1)


@pytest.mark.asyncio
async def test_context_rejects_child_after_dispose():
    ctx = PluginContext()
    await ctx.dispose()
    with pytest.raises(RuntimeError):
        ctx.child()


# --- BackgroundTask helper --------------------------------------------------------


@pytest.mark.asyncio
async def test_background_task_helper():
    async def coro():
        await asyncio.sleep(100)

    task = asyncio.create_task(coro())
    bg = BackgroundTask(task)
    bg.cancel()
    await asyncio.sleep(0.05)
    assert task.cancelled() or task.done()

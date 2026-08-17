"""Phase 5 — Bootstrap Switch tests.

Covers the production bootstrap chain:

    load profile → Plugin Bootstrap → Runtime + Shared + mode.learn

and the Phase 5 requirements:

* production Profile boots every Runtime / Shared / mode.learn service;
* ``mode.learn`` consumes the shared services injected through the
  PluginContext (no global-registry lookup at runtime);
* Profile Binding wires the real LLM / Retrieval providers;
* ``mastery_path`` is only a compatibility entry mapped to ``mode.learn``;
* full lifecycle: boot → run → dispose (idempotent shutdown);
* bootstrap failure rolls back every previously-registered service.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lumen.bootstrap import LumenBootstrap, boot_lumen
from lumen.compat import resolve_learn_mode
from lumen.modes.learn import LearnModeService
from lumen.modes.learn.plugin import _LearnModeServiceAdapter
from lumen.profile import PRODUCTION_PLUGINS, PRODUCTION_PROFILE
from lumen.runtime.agent_loop.providers.legacy.plugin import _AgentLoopServiceAdapter
from lumen.runtime.llm.plugin import _LLMServiceAdapter
from lumen.runtime.tools.plugin import _ToolServiceAdapter
from lumen.shared.knowledge.retrieval.plugin import _KnowledgeRetrievalServiceAdapter
from lumen.shared.memory.plugin import _MemoryServiceAdapter
from lumen.shared.notebook.plugin import _NotebookServiceAdapter

# ═══════════════════════════════════════════════════════════════════════════
# 1. Production Profile declares the canonical set
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED_SERVICES = [
    # Runtime
    "runtime.session",
    "runtime.prompt",
    "runtime.tools",
    "runtime.llm",
    "runtime.agent",
    "runtime.agent_loop",
    # Shared
    "knowledge.sources",
    "knowledge.retrieval",
    "knowledge.parsing",
    "memory",
    "notebook",
    "rendering",
    # Modes
    "mode.learn",
]


def test_production_profile_declares_canonical_set():
    ids = [plugin.manifest.id for plugin in PRODUCTION_PLUGINS]
    assert ids == [
        "runtime.session",
        "runtime.prompt",
        "runtime.tools",
        "runtime.llm",
        "runtime.agent",
        "runtime.agent_loop",
        "knowledge.sources",
        "knowledge.retrieval",
        "knowledge.parsing",
        "memory",
        "notebook",
        "rendering",
        "mode.learn",
    ]
    assert len(ids) == len(set(ids))  # no duplicates


def test_production_profile_selects_every_plugin():
    selected = {m.id for m in PRODUCTION_PROFILE.select([p.manifest for p in PRODUCTION_PLUGINS])}
    assert selected == set(EXPECTED_SERVICES)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Production Profile boots all Runtime + Shared + mode.learn services
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_production_profile_boots_all_services():
    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()

    try:
        for service in EXPECTED_SERVICES:
            assert root.optional(service) is not None, f"missing service: {service}"

        assert isinstance(root.require("mode.learn"), LearnModeService)
    finally:
        await bootstrap.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 3. mode.learn consumes injected Shared / Runtime services (not globals)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mode_learn_uses_injected_shared_services():
    """The adapter registered as ``mode.learn`` must hold the very same
    service instances the kernel provided — proving constructor injection
    rather than a global-registry lookup."""
    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()

    try:
        mode_learn = root.require("mode.learn")
        assert isinstance(mode_learn, _LearnModeServiceAdapter)

        # Every injected dependency is the kernel-provided instance.
        assert mode_learn._memory_service is root.require("memory")
        assert mode_learn._notebook_service is root.require("notebook")
        assert mode_learn._knowledge_sources is root.require("knowledge.sources")
        assert mode_learn._knowledge_retrieval is root.require("knowledge.retrieval")
        assert mode_learn._tools_service is root.require("runtime.tools")
        assert mode_learn._llm_service is root.require("runtime.llm")
    finally:
        await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_pipeline_deps_forward_injected_services():
    """The mode.learn adapter forwards each injected shared service into the
    agent pipeline as a constructor argument — no monkey patching."""
    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()

    try:
        mode_learn = root.require("mode.learn")
        deps = mode_learn._pipeline_deps()

        assert deps["memory_service"] is root.require("memory")
        assert deps["notebook_service"] is root.require("notebook")
        assert deps["knowledge_sources"] is root.require("knowledge.sources")
        assert deps["knowledge_retrieval"] is root.require("knowledge.retrieval")
        assert deps["registry"] is root.require("runtime.tools")
        # client_factory is the runtime.llm contract's client builder.
        assert callable(deps["client_factory"])
    finally:
        await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_mode_learn_turn_runs_through_injected_agent_loop(tmp_path):
    """handle_turn() drives the injected runtime.agent_loop and records the
    learner state through the existing learning engine."""
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.stream_bus import StreamBus
    from deeptutor.learning.storage import LearningStore

    store = LearningStore(root=tmp_path)
    calls: list[tuple[Any, Any, str, dict[str, Any]]] = []

    class FakeAgentLoop:
        async def run(self, *, context, stream, language="en", **config):
            calls.append((context, stream, language, config))

    adapter = _LearnModeServiceAdapter(agent_loop=FakeAgentLoop(), store=store)
    ctx = UnifiedContext(session_id="phase5-session", user_message="teach me")
    bus = StreamBus()

    await adapter.handle_turn(ctx, bus)

    assert len(calls) == 1
    context, stream, language, config = calls[0]
    assert context is ctx
    assert stream is bus
    assert language == "en"
    assert ctx.metadata.get("mastery_mode") is True
    assert ctx.metadata.get("mastery_path_id") == "phase5-session"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Profile Binding wires the real LLM / Retrieval providers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_production_binding_uses_real_llm_and_retrieval():
    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()

    try:
        assert isinstance(root.require("runtime.llm"), _LLMServiceAdapter)
        assert isinstance(
            root.require("knowledge.retrieval"), _KnowledgeRetrievalServiceAdapter
        )
        assert isinstance(root.require("runtime.tools"), _ToolServiceAdapter)
        assert isinstance(root.require("memory"), _MemoryServiceAdapter)
        assert isinstance(root.require("notebook"), _NotebookServiceAdapter)
    finally:
        await bootstrap.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 5. mastery_path → mode.learn compatibility mapping
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("capability", "expected"),
    [
        ("mastery_path", "mode.learn"),
        ("mastery", "mode.learn"),
        ("mode.learn", "mode.learn"),
        ("chat", "chat"),
        (None, None),
    ],
)
def test_resolve_learn_mode_mapping(capability, expected):
    assert resolve_learn_mode(capability) == expected


def test_mastery_path_is_not_a_top_level_product_capability():
    """mode.learn is the only learn abstraction in the production profile;
    mastery_path is NOT declared as a plugin service."""
    provides = {p for p in PRODUCTION_PLUGINS for p in p.manifest.provides}
    assert "mode.learn" in provides
    assert "mastery_path" not in provides


@pytest.mark.asyncio
async def test_bootstrap_resolve_mode_maps_legacy_names():
    bootstrap = LumenBootstrap()
    assert bootstrap.resolve_mode("mastery_path") == "mode.learn"
    assert bootstrap.resolve_mode("mastery") == "mode.learn"
    assert bootstrap.resolve_mode("mode.learn") == "mode.learn"
    assert bootstrap.resolve_mode("chat") == "chat"
    assert bootstrap.resolve_mode(None) == "chat"
    await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_bootstrap_learn_service_resolves_kernel_mode_learn():
    """The new entry layer maps legacy mastery_path onto the kernel's
    mode.learn service — the only Learn product abstraction."""
    bootstrap = LumenBootstrap()
    await bootstrap.boot()
    try:
        assert bootstrap.learn_service("mastery_path") is not None
        assert bootstrap.learn_service("mastery") is not None
        assert bootstrap.learn_service("mode.learn") is not None
        # Non-learn requests never resolve to the learn service.
        assert bootstrap.learn_service("chat") is None
    finally:
        await bootstrap.shutdown()

    # After shutdown the kernel is gone — no service to resolve.
    assert bootstrap.learn_service("mastery_path") is None


# ═══════════════════════════════════════════════════════════════════════════
# 6. Lifecycle — boot / run / dispose
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_boot_is_idempotent():
    bootstrap = LumenBootstrap()
    root1 = await bootstrap.boot()
    root2 = await bootstrap.boot()
    assert root1 is root2
    await bootstrap.shutdown()


@pytest.mark.asyncio
async def test_shutdown_disposes_and_is_idempotent():
    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()
    assert root.disposed is False

    await bootstrap.shutdown()
    assert root.disposed is True
    assert bootstrap.root is None

    # second shutdown is a no-op
    await bootstrap.shutdown()
    assert bootstrap.root is None


@pytest.mark.asyncio
async def test_boot_lumen_convenience():
    root = await boot_lumen()
    try:
        assert root.optional("mode.learn") is not None
    finally:
        await root.dispose()
    assert root.disposed


@pytest.mark.asyncio
async def test_lifecycle_boot_run_dispose_roundtrip(tmp_path):
    """Full lifecycle: boot → start learner → turn → state → dispose."""
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.stream_bus import StreamBus

    bootstrap = LumenBootstrap()
    root = await bootstrap.boot()
    try:
        mode_learn = root.require("mode.learn")
        await mode_learn.start("algebra-basics")
        state = await mode_learn.get_state("algebra-basics")
        assert state["book_id"] == "algebra-basics"

        # The turn flows through the injected agent loop; a fake LLM is not
        # required here because handle_turn only wires the pipeline — the
        # actual LLM call happens inside the loop's turn execution, which we
        # don't drive in this unit test.
        ctx = UnifiedContext(session_id="algebra-basics", user_message="start lesson")
        bus = StreamBus()
        await mode_learn.handle_turn(ctx, bus)
        assert ctx.metadata.get("mastery_mode") is True
    finally:
        await bootstrap.shutdown()
    assert root.disposed


# ═══════════════════════════════════════════════════════════════════════════
# 7. Bootstrap failure rolls back every registered service
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bootstrap_failure_rolls_back_services():
    """A failing plugin must tear down every service that already booted,
    leaving nothing registered."""
    from lumen.kernel import Plugin, PluginContext, PluginManifest, Profile

    rolled_back: list[str] = []

    class OkPlugin(Plugin):
        manifest = PluginManifest(id="ok", provides=["svc_ok"])

        async def setup(self, ctx: PluginContext) -> None:
            ctx.provide("svc_ok", "ok")
            ctx.on_dispose(lambda: rolled_back.append("svc_ok"))

    class BoomPlugin(Plugin):
        manifest = PluginManifest(id="boom", requires=["svc_ok"])

        async def setup(self, ctx: PluginContext) -> None:
            raise RuntimeError("boom during setup")

    bootstrap = LumenBootstrap(profile=Profile(), plugins=[OkPlugin(), BoomPlugin()])
    with pytest.raises(RuntimeError, match="boom"):
        await bootstrap.boot()

    assert rolled_back == ["svc_ok"]
    assert bootstrap.root is None

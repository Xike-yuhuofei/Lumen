"""Tests for Runtime Adapter Plugins (Phase 2).

Covers service registration, dependency ordering, replaceability,
lifecycle, and rollback for the runtime plugin set.
"""

from __future__ import annotations

from typing import Any

import pytest

from lumen.kernel import (
    Bootstrap,
    DependencyResolver,
    Plugin,
    PluginContext,
    PluginManifest,
    Profile,
)
from lumen.runtime import (
    AgentLoopPlugin,
    AgentPlugin,
    LLMPlugin,
    PromptPlugin,
    SessionPlugin,
    ToolPlugin,
)
from tests.kernel.fakes import FakeLLMPlugin, FakeLLMService

# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════


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


#: All runtime plugins wired together with a fake LLM — the test profile.
RUNTIME_TEST_PLUGINS = [
    SessionPlugin(),
    PromptPlugin(),
    ToolPlugin(),
    FakeLLMPlugin(responses=["fake response"]),
    AgentPlugin(),
    AgentLoopPlugin(),
]

RUNTIME_TEST_PROFILE = Profile(
    manifests=[
        PluginManifest(id="runtime.session"),
        PluginManifest(id="runtime.prompt"),
        PluginManifest(id="runtime.tools"),
        PluginManifest(id="llm.fake", provides=["runtime.llm"]),
        PluginManifest(id="runtime.agent"),
        PluginManifest(id="runtime.agent_loop"),
    ],
    bindings={"runtime.llm": "llm.fake"},
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Each Runtime Plugin can register and provide its service
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_plugin_provides_service():
    ctx = PluginContext()
    session = SessionPlugin()
    await session.setup(ctx)
    svc = ctx.optional("runtime.session")
    assert svc is not None
    # Check the adapter is structurally sound (lazy-init won't crash)
    import inspect

    assert hasattr(svc, "ensure_session")
    assert hasattr(svc, "start_turn")
    assert hasattr(svc, "cancel_turn")
    assert hasattr(svc, "subscribe_turn")
    await ctx.dispose()


@pytest.mark.asyncio
async def test_prompt_plugin_provides_service():
    ctx = PluginContext()
    await PromptPlugin().setup(ctx)
    svc = ctx.optional("runtime.prompt")
    assert svc is not None
    assert hasattr(svc, "load_prompt")
    await ctx.dispose()


@pytest.mark.asyncio
async def test_tool_plugin_provides_service():
    ctx = PluginContext()
    await ToolPlugin().setup(ctx)
    svc = ctx.optional("runtime.tools")
    assert svc is not None
    assert hasattr(svc, "get")
    assert hasattr(svc, "execute")
    assert hasattr(svc, "build_openai_schemas")
    await ctx.dispose()


@pytest.mark.asyncio
async def test_llm_plugin_provides_service():
    ctx = PluginContext()
    await LLMPlugin().setup(ctx)
    svc = ctx.optional("runtime.llm")
    assert svc is not None
    assert hasattr(svc, "build_openai_client")
    assert hasattr(svc, "complete")
    await ctx.dispose()


@pytest.mark.asyncio
async def test_fake_llm_plugin_provides_service():
    ctx = PluginContext()
    await FakeLLMPlugin(responses=["hello"]).setup(ctx)
    svc = ctx.require("runtime.llm")
    assert isinstance(svc, FakeLLMService)
    result = await svc.complete([{"role": "user", "content": "hi"}])
    assert result == "hello"
    await ctx.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Dependency order is correct
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_plugin_requires_tools_prompt_llm():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(
            id="runtime.agent",
            provides=["runtime.agent"],
            requires=["runtime.tools", "runtime.prompt", "runtime.llm"],
        ),
        PluginManifest(id="runtime.tools", provides=["runtime.tools"]),
        PluginManifest(id="runtime.prompt", provides=["runtime.prompt"]),
        PluginManifest(id="runtime.llm", provides=["runtime.llm"]),
    ]
    ordered = resolver.resolve(manifests)
    ids = [m.id for m in ordered]
    # runtime.agent must come after its dependencies
    assert ids.index("runtime.agent") > ids.index("runtime.tools")
    assert ids.index("runtime.agent") > ids.index("runtime.prompt")
    assert ids.index("runtime.agent") > ids.index("runtime.llm")


def test_agent_loop_requires_all_services():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(
            id="runtime.agent_loop",
            provides=["runtime.agent_loop"],
            requires=[
                "runtime.agent",
                "runtime.session",
                "runtime.llm",
                "runtime.tools",
                "runtime.prompt",
            ],
        ),
        PluginManifest(
            id="runtime.agent",
            provides=["runtime.agent"],
            requires=["runtime.tools", "runtime.prompt", "runtime.llm"],
        ),
        PluginManifest(id="runtime.session", provides=["runtime.session"]),
        PluginManifest(id="runtime.tools", provides=["runtime.tools"]),
        PluginManifest(id="runtime.prompt", provides=["runtime.prompt"]),
        PluginManifest(id="runtime.llm", provides=["runtime.llm"]),
    ]
    ordered = resolver.resolve(manifests)
    ids = [m.id for m in ordered]
    assert ids.index("runtime.agent_loop") > ids.index("runtime.agent")
    assert ids.index("runtime.agent_loop") > ids.index("runtime.session")
    assert ids.index("runtime.agent_loop") > ids.index("runtime.llm")
    assert ids.index("runtime.agent_loop") > ids.index("runtime.tools")
    assert ids.index("runtime.agent_loop") > ids.index("runtime.prompt")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Missing runtime dependency prevents boot
# ═══════════════════════════════════════════════════════════════════════════


def test_missing_runtime_tools_prevents_agent():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="runtime.agent", provides=["runtime.agent"], requires=["runtime.tools"]),
        # runtime.tools is missing
    ]
    with pytest.raises(RuntimeError, match="missing dependency"):
        resolver.resolve(manifests)


def test_missing_llm_dependency_blocks_boot():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(
            id="runtime.agent_loop", provides=["runtime.agent_loop"], requires=["runtime.llm"]
        ),
        # runtime.llm is missing
    ]
    with pytest.raises(RuntimeError, match="missing dependency"):
        resolver.resolve(manifests)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Runtime Test Profile can fully boot / dispose
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_runtime_test_profile_boots_completely():
    root = await Bootstrap(profile=RUNTIME_TEST_PROFILE).boot(RUNTIME_TEST_PLUGINS)
    assert root.optional("runtime.session") is not None
    assert root.optional("runtime.prompt") is not None
    assert root.optional("runtime.tools") is not None
    assert root.optional("runtime.llm") is not None
    assert root.optional("runtime.agent") is not None
    assert root.optional("runtime.agent_loop") is not None
    # Fake LLM is the elected provider
    svc = root.require("runtime.llm")
    assert isinstance(svc, FakeLLMService)
    await root.dispose()
    assert root.disposed


@pytest.mark.asyncio
async def test_runtime_test_profile_dispose_removes_all_services():
    root = await Bootstrap(profile=RUNTIME_TEST_PROFILE).boot(RUNTIME_TEST_PLUGINS)
    await root.dispose()
    with pytest.raises(LookupError):
        root.require("runtime.session")
    with pytest.raises(LookupError):
        root.require("runtime.prompt")
    with pytest.raises(LookupError):
        root.require("runtime.tools")
    with pytest.raises(LookupError):
        root.require("runtime.llm")
    with pytest.raises(LookupError):
        root.require("runtime.agent")
    with pytest.raises(LookupError):
        root.require("runtime.agent_loop")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Fake LLM provider can replace real LLM via binding
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fake_llm_replaces_real_llm_through_binding():
    """When both LLMPlugin and FakeLLMPlugin provide runtime.llm, the
    profile binding elects the fake one. The Agent Loop plugin depends
    on runtime.llm without caring which provider is active."""

    plugins = [
        LLMPlugin(),
        FakeLLMPlugin(responses=["replaced by fake"]),
        SessionPlugin(),
        PromptPlugin(),
        ToolPlugin(),
        AgentPlugin(),
        AgentLoopPlugin(),
    ]
    profile = Profile(
        bindings={"runtime.llm": "llm.fake"},
    )
    root = await Bootstrap(profile=profile).boot(plugins)
    llm = root.require("runtime.llm")
    assert isinstance(llm, FakeLLMService)
    result = await llm.complete([{"role": "user", "content": "test"}])
    assert result == "replaced by fake"
    await root.dispose()


@pytest.mark.asyncio
async def test_agent_loop_does_not_depend_on_specific_llm_provider():
    """The AgentLoopPlugin requires runtime.llm generically — it does not
    know or care whether the provider is FakeLLMPlugin or LLMPlugin."""

    manifest = AgentLoopPlugin.manifest
    assert "runtime.llm" in manifest.requires
    assert "llm.fake" not in manifest.requires
    assert "runtime.llm" not in manifest.provides


@pytest.mark.asyncio
async def test_agent_loop_runner_injects_client_through_runtime_llm_contract():
    """The agent-loop runner obtains its OpenAI-compatible client solely via
    the ``runtime.llm`` contract (``build_openai_client``), so swapping the
    bound provider never touches the consumer."""

    from lumen.runtime.agent_loop.providers.legacy.plugin import _AgentLoopServiceAdapter

    built_with: list[Any] = []
    ran_with: list[Any] = []

    class FakeAgentService:
        async def create_pipeline(self, language: str = "en", **config: Any):
            client_factory = config.get("client_factory")

            class FakePipeline:
                _client_config = "fake-config"
                _client_factory = client_factory

                async def run(self, context, stream):
                    ran_with.append(context)
                    # The real pipeline builds its client through
                    # _build_openai_client, which delegates to _client_factory
                    # when set — exactly the seam the adapter injects.
                    self._build_openai_client()

                def _build_openai_client(self):
                    if self._client_factory is not None:
                        return self._client_factory(self._client_config)
                    raise RuntimeError("no client factory injected")

            return FakePipeline()

    class FakeLLMService:
        def build_openai_client(self, config):
            built_with.append(config)
            return "fake-client-object"

    adapter = _AgentLoopServiceAdapter(FakeAgentService(), FakeLLMService())
    await adapter.run(context="ctx", stream="stream", language="en")
    assert built_with == ["fake-config"]
    assert ran_with == ["ctx"]


@pytest.mark.asyncio
async def test_adapter_injection_coexists_with_existing_monkeypatch_pattern(
    monkeypatch: pytest.MonkeyPatch,
):
    """Existing tests monkeypatch ``pipeline._build_openai_client`` directly
    (e.g. ``tests/agents/chat/test_agent_loop.py``). The adapter's constructor
    injection must not break that pattern — a monkeypatched instance attribute
    still wins over the ``_client_factory`` seam."""

    from lumen.runtime.agent_loop.providers.legacy.agent import _AgentServiceAdapter

    registry = object()
    adapter = _AgentServiceAdapter(
        tool_service=registry,
        prompt_service=object(),
        llm_service=object(),
    )
    # registry is injected via the constructor (debt #2 resolved)
    pipeline = await adapter.create_pipeline(language="en")
    assert pipeline.registry is registry

    # then monkeypatch the client seam like legacy tests do — it still wins
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: "monkeypatched-client")
    assert pipeline._build_openai_client() == "monkeypatched-client"


@pytest.mark.asyncio
async def test_pipeline_constructor_accepts_client_factory():
    """The real ``AgenticChatPipeline`` accepts a ``client_factory``
    constructor hook (Phase 3 debt #1/#2: no more monkey-patching)."""

    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline

    called: list[Any] = []

    def factory(config: Any) -> str:
        called.append(config)
        return "injected-client"

    pipeline = AgenticChatPipeline(language="en", client_factory=factory)
    assert pipeline._build_openai_client() == "injected-client"
    assert called  # the factory received the pipeline's client config


# ═══════════════════════════════════════════════════════════════════════════
# 6. Role-based Contract boundary — runtime plugins only depend on
#    service contracts, not on concrete implementations
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_plugin_declares_only_contracts_not_implementations():
    manifest = AgentPlugin.manifest
    # Must depend on the LLM contract, not on a specific provider
    assert "runtime.llm" in manifest.requires
    assert "llm.fake" not in manifest.requires
    assert "runtime.llm" not in manifest.provides
    assert "runtime.agent" in manifest.provides


def test_agent_loop_plugin_declares_contracts_not_providers():
    manifest = AgentLoopPlugin.manifest
    assert "runtime.llm" in manifest.requires
    assert "llm.fake" not in manifest.requires
    assert "runtime.agent_loop" in manifest.provides


# ═══════════════════════════════════════════════════════════════════════════
# 7. Setup partial failure rolls back completely
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_runtime_partial_setup_failure_rolls_back():
    """If a runtime plugin fails during setup, already-registered services
    are cleaned up via their disposal callbacks."""

    rolled_back: list[str] = []

    class OkPlugin(Plugin):
        manifest = PluginManifest(id="ok", provides=["svc_ok"])

        async def setup(self, ctx: PluginContext) -> None:
            ctx.provide("svc_ok", "ok")
            ctx.on_dispose(lambda: rolled_back.append("ok"))

    class BoomPlugin(Plugin):
        manifest = PluginManifest(id="boom", requires=["svc_ok"])

        async def setup(self, ctx: PluginContext) -> None:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await Bootstrap().boot([OkPlugin(), BoomPlugin()])

    # the already-started "ok" plugin was fully rolled back
    assert rolled_back == ["ok"]


# ═══════════════════════════════════════════════════════════════════════════
# 8. Async teardown leaves no residual service
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_runtime_teardown_clears_all_services():
    root = await Bootstrap(profile=RUNTIME_TEST_PROFILE).boot(RUNTIME_TEST_PLUGINS)
    assert root.optional("runtime.session") is not None
    await root.dispose()
    # After dispose, all services are gone
    for name in [
        "runtime.session",
        "runtime.prompt",
        "runtime.tools",
        "runtime.llm",
        "runtime.agent",
        "runtime.agent_loop",
    ]:
        assert root.optional(name) is None, f"{name} survived dispose"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Kernel isolation — runtime adapter does not break kernel's domain
#    freedom
# ═══════════════════════════════════════════════════════════════════════════


def test_runtime_adapter_imports_dont_break_kernel_isolation():
    """Importing lumen.runtime must not cause lumen.kernel to import
    domain modules."""
    import lumen.kernel

    for _finder, name, _is_pkg in __import__("pkgutil").iter_modules(lumen.kernel.__path__):
        module = __import__("importlib").import_module(f"lumen.kernel.{name}")
        source_file = getattr(module, "__file__", "")
        if not source_file:
            continue
        source = open(source_file).read().lower()
        for domain in ["llm", "rag", "memory", "learn", "teaching", "news", "review", "agent"]:
            assert domain not in source, (
                f"lumen.kernel.{name} references forbidden domain '{domain}'"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 10. Plugin dispose does not raise after context is disposed
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_runtime_dispose_idempotent():
    root = await Bootstrap(profile=RUNTIME_TEST_PROFILE).boot(RUNTIME_TEST_PLUGINS)
    await root.dispose()
    await root.dispose()  # second call is a no-op
    assert root.disposed

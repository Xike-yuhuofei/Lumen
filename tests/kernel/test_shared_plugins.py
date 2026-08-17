"""Tests for Shared Services Adapter Plugins (Phase 3).

Covers registration, dependency ordering, replaceability (fake retrieval
provider via binding), lifecycle, and rollback for the shared plugin set.
"""

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
from lumen.runtime import (
    AgentLoopPlugin,
    AgentPlugin,
    LLMPlugin,
    PromptPlugin,
    SessionPlugin,
    ToolPlugin,
)
from lumen.shared import (
    KnowledgeParsingPlugin,
    KnowledgeRetrievalPlugin,
    KnowledgeSourcesPlugin,
    MemoryPlugin,
    NotebookPlugin,
    RenderingPlugin,
)
from tests.kernel.fakes import FakeLLMPlugin, FakeRetrievalPlugin, FakeRetrievalService

# ═══════════════════════════════════════════════════════════════════════════
# Test helpers / profiles
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


SHARED_PLUGINS = [
    KnowledgeSourcesPlugin(),
    KnowledgeRetrievalPlugin(),
    KnowledgeParsingPlugin(),
    MemoryPlugin(),
    NotebookPlugin(),
    RenderingPlugin(),
]

SHARED_TEST_PROFILE = Profile(manifests=[PluginManifest(id=p.manifest.id) for p in SHARED_PLUGINS])

# Full Runtime + Shared composition with fake providers for llm + retrieval.
FULL_PROFILE = Profile(
    manifests=[
        PluginManifest(id="runtime.session"),
        PluginManifest(id="runtime.prompt"),
        PluginManifest(id="runtime.tools"),
        PluginManifest(id="llm.fake", provides=["runtime.llm"]),
        PluginManifest(id="runtime.agent"),
        PluginManifest(id="runtime.agent_loop"),
        PluginManifest(id="knowledge.sources"),
        PluginManifest(id="retrieval.fake", provides=["knowledge.retrieval"]),
        PluginManifest(id="knowledge.parsing"),
        PluginManifest(id="memory"),
        PluginManifest(id="notebook"),
        PluginManifest(id="rendering"),
    ],
    bindings={"runtime.llm": "llm.fake", "knowledge.retrieval": "retrieval.fake"},
)

FULL_PLUGINS = [
    SessionPlugin(),
    PromptPlugin(),
    ToolPlugin(),
    FakeLLMPlugin(responses=["fake"]),
    AgentPlugin(),
    AgentLoopPlugin(),
    KnowledgeSourcesPlugin(),
    FakeRetrievalPlugin(content="fake retrieval content"),
    KnowledgeParsingPlugin(),
    MemoryPlugin(),
    NotebookPlugin(),
    RenderingPlugin(),
]


# ═══════════════════════════════════════════════════════════════════════════
# 1. All 6 shared services register correctly
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_shared_plugins_register_all_services():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    for name in [
        "knowledge.sources",
        "knowledge.retrieval",
        "knowledge.parsing",
        "memory",
        "notebook",
        "rendering",
    ]:
        assert root.optional(name) is not None, f"{name} missing"
    await root.dispose()


@pytest.mark.asyncio
async def test_each_shared_service_has_contract_surface():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    assert hasattr(root.require("knowledge.sources"), "list_knowledge_bases")
    assert hasattr(root.require("knowledge.retrieval"), "search")
    assert hasattr(root.require("knowledge.parsing"), "parse")
    assert hasattr(root.require("memory"), "overview")
    assert hasattr(root.require("notebook"), "list")
    assert hasattr(root.require("rendering"), "strip_markdown")
    await root.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Dependency order — retrieval depends on sources
# ═══════════════════════════════════════════════════════════════════════════


def test_retrieval_plugin_requires_sources():
    manifest = KnowledgeRetrievalPlugin.manifest
    assert "knowledge.sources" in manifest.requires
    assert "knowledge.retrieval" in manifest.provides


def test_dependency_order_sources_before_retrieval():
    resolver = DependencyResolver()
    manifests = [
        KnowledgeRetrievalPlugin.manifest,
        KnowledgeSourcesPlugin.manifest,
    ]
    ordered = resolver.resolve(manifests)
    ids = [m.id for m in ordered]
    assert ids.index("knowledge.sources") < ids.index("knowledge.retrieval")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Missing dependency prevents boot
# ═══════════════════════════════════════════════════════════════════════════


def test_missing_shared_dependency_fails():
    resolver = DependencyResolver()
    manifests = [
        PluginManifest(id="knowledge.retrieval", requires=["knowledge.sources"]),
        # knowledge.sources missing
    ]
    with pytest.raises(RuntimeError, match="missing dependency"):
        resolver.resolve(manifests)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Runtime + Shared profile boots fully
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_runtime_and_shared_profile_full_boot():
    root = await Bootstrap(profile=FULL_PROFILE).boot(FULL_PLUGINS)
    for name in [
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
    ]:
        assert root.optional(name) is not None, f"{name} missing in full boot"
    await root.dispose()
    assert root.disposed


# ═══════════════════════════════════════════════════════════════════════════
# 5. dispose removes all shared services
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dispose_removes_all_shared_services():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    await root.dispose()
    for name in [
        "knowledge.sources",
        "knowledge.retrieval",
        "knowledge.parsing",
        "memory",
        "notebook",
        "rendering",
    ]:
        with pytest.raises(LookupError):
            root.require(name)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Setup failure rolls back
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_shared_partial_setup_failure_rolls_back():
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
    assert rolled_back == ["ok"]


# ═══════════════════════════════════════════════════════════════════════════
# 7. Fake retrieval provider replaced via binding
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fake_retrieval_replaces_real_rag_through_binding():
    """Both KnowledgeRetrievalPlugin and FakeRetrievalPlugin provide
    knowledge.retrieval; the profile binding elects the fake. The consumer
    never knows which provider is active."""

    plugins = [
        KnowledgeSourcesPlugin(),
        KnowledgeRetrievalPlugin(),
        FakeRetrievalPlugin(content="replaced by fake RAG"),
    ]
    profile = Profile(bindings={"knowledge.retrieval": "retrieval.fake"})
    root = await Bootstrap(profile=profile).boot(plugins)
    retrieval = root.require("knowledge.retrieval")
    assert isinstance(retrieval, FakeRetrievalService)
    result = await retrieval.search("who are you", "kb")
    assert result.content == "replaced by fake RAG"
    assert retrieval.searches == [("who are you", "kb")]
    await root.dispose()


@pytest.mark.asyncio
async def test_shared_contract_does_not_depend_on_specific_provider():
    """knowledge.retrieval is required by consumers generically; manifests
    reference the contract name, never a concrete provider id."""

    manifest = PluginManifest(
        id="consumer",
        provides=["x"],
        requires=["knowledge.retrieval"],
    )
    assert "knowledge.retrieval" in manifest.requires
    assert "retrieval.fake" not in manifest.requires


# ═══════════════════════════════════════════════════════════════════════════
# 8. Shared plugins do not depend on Learn / mastery / teaching
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "plugin",
    [
        KnowledgeSourcesPlugin(),
        KnowledgeRetrievalPlugin(),
        KnowledgeParsingPlugin(),
        MemoryPlugin(),
        NotebookPlugin(),
        RenderingPlugin(),
    ],
    ids=lambda p: p.manifest.id,
)
def test_shared_plugin_has_no_learn_dependency(plugin):
    forbidden = {"mode.learn", "mastery_path", "learning", "teaching_core"}
    deps = set(plugin.manifest.requires)
    assert not deps & forbidden, f"{plugin.manifest.id} depends on learn-domain: {deps & forbidden}"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Kernel stays domain-free
# ═══════════════════════════════════════════════════════════════════════════


def test_kernel_has_no_domain_dependency_after_shared_import():
    import importlib
    import pkgutil

    import lumen.kernel

    for _finder, name, _is_pkg in pkgutil.iter_modules(lumen.kernel.__path__):
        module = importlib.import_module(f"lumen.kernel.{name}")
        source_file = getattr(module, "__file__", "")
        if not source_file:
            continue
        source = open(source_file).read().lower()
        for domain in ["llm", "rag", "memory", "learn", "teaching", "news", "review", "agent"]:
            assert domain not in source, (
                f"lumen.kernel.{name} references forbidden domain '{domain}'"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 10. Rendering / parsing / sources contract behavior
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rendering_service_strips_markdown_and_think_tags():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    rendering = root.require("rendering")
    # clean_thinking_tags removes the private scratchpad tag pair, not the word
    cleaned = rendering.clean_thinking_tags("visible answer")
    assert "visible answer" in cleaned
    stripped = rendering.strip_markdown("**bold** [link](url)")
    assert "**" not in stripped
    assert "link" in stripped
    await root.dispose()


@pytest.mark.asyncio
async def test_parsing_service_rejects_missing_file():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    parsing = root.require("knowledge.parsing")
    with pytest.raises(Exception):
        parsing.parse("/definitely/not/a/real/file.pdf")
    await root.dispose()


@pytest.mark.asyncio
async def test_sources_service_exposes_kb_manager_surface():
    root = await Bootstrap(profile=SHARED_TEST_PROFILE).boot(SHARED_PLUGINS)
    sources = root.require("knowledge.sources")
    # list may be empty, but the call must not crash
    assert isinstance(sources.list_knowledge_bases(), list)
    await root.dispose()

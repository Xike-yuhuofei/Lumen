"""Tests for ``mode.learn`` plugin (Phase 4).

Covers registration, dependency isolation, full profile boot, the minimal
teaching flow (start -> state -> handle_turn -> get_state), binding
replaceability, lifecycle, and rollback.
"""

from __future__ import annotations

import asyncio
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
from lumen.modes.learn import LearnModeService, ModeLearnPlugin
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
from tests.kernel.fakes import FakeLLMPlugin, FakeRetrievalPlugin

# ═══════════════════════════════════════════════════════════════════════════
# Full profile: Runtime + Shared + mode.learn (fake llm + fake retrieval)
# ═══════════════════════════════════════════════════════════════════════════

LEARN_PROFILE = Profile(
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
        PluginManifest(id="mode.learn"),
    ],
    bindings={"runtime.llm": "llm.fake", "knowledge.retrieval": "retrieval.fake"},
)

LEARN_PLUGINS = [
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
    ModeLearnPlugin(),
]


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


# ═══════════════════════════════════════════════════════════════════════════
# 1. mode.learn registers correctly
# ═══════════════════════════════════════════════════════════════════════════


def test_mode_learn_manifest():
    manifest = ModeLearnPlugin.manifest
    assert manifest.id == "mode.learn"
    assert "mode.learn" in manifest.provides
    for required in [
        "runtime.agent_loop",
        "runtime.session",
        "runtime.llm",
        "runtime.tools",
        "knowledge.sources",
        "knowledge.retrieval",
        "memory",
        "notebook",
    ]:
        assert required in manifest.requires


def test_mode_learn_does_not_depend_on_provider_implementations():
    manifest = ModeLearnPlugin.manifest
    forbidden = {"retrieval.fake", "llm.fake", "runtime.agent"}
    assert not set(manifest.requires) & forbidden


# ═══════════════════════════════════════════════════════════════════════════
# 2. dependency isolation — requires only contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_mode_learn_requires_only_contracts():
    manifest = ModeLearnPlugin.manifest
    deps = set(manifest.requires)
    assert deps <= {
        "runtime.agent_loop",
        "runtime.session",
        "runtime.llm",
        "runtime.tools",
        "knowledge.sources",
        "knowledge.retrieval",
        "memory",
        "notebook",
    }


def test_mode_learn_has_no_learn_internal_dependency():
    """mode.learn must not require learning/ / teaching_core / mastery_path
    as plugin services — it *wraps* them, it does not compose them."""

    manifest = ModeLearnPlugin.manifest
    forbidden = {"learning", "teaching_core", "mastery_path"}
    assert not set(manifest.requires) & forbidden


# ═══════════════════════════════════════════════════════════════════════════
# 3. Missing dependency prevents boot
# ═══════════════════════════════════════════════════════════════════════════


def test_missing_dependency_prevents_mode_learn_boot():
    resolver = DependencyResolver()
    manifests = [ModeLearnPlugin.manifest]
    with pytest.raises(RuntimeError, match="missing dependency"):
        resolver.resolve(manifests)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Full Runtime + Shared + Learn profile boots
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_profile_boots_with_mode_learn():
    root = await Bootstrap(profile=LEARN_PROFILE).boot(LEARN_PLUGINS)
    assert root.optional("mode.learn") is not None
    assert isinstance(root.require("mode.learn"), LearnModeService)
    await root.dispose()
    assert root.disposed


# ═══════════════════════════════════════════════════════════════════════════
# 5. Minimal real teaching flow — start / get_state / resume
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_learn_start_get_state_resume(tmp_path):
    """start() persists a learner path through the real LearningStore;
    get_state() / resume() read it back."""

    from lumen.modes.learn.adapters.storage import LearningStore

    store = LearningStore(root=tmp_path)
    from lumen.modes.learn.plugin import _LearnModeServiceAdapter

    adapter = _LearnModeServiceAdapter(agent_loop=object(), store=store)

    state = await adapter.start("algebra-basics")
    assert state["book_id"] == "algebra-basics"

    state_again = await adapter.get_state("algebra-basics")
    assert state_again["book_id"] == "algebra-basics"

    resumed = await adapter.resume("algebra-basics")
    assert resumed is not None
    assert resumed["book_id"] == "algebra-basics"

    missing = await adapter.resume("does-not-exist")
    assert missing is None
    assert await adapter.get_state("does-not-exist") == {}


@pytest.mark.asyncio
async def test_learn_state_is_mutable_through_engine(tmp_path):
    """Updating mastery through the existing engine is reflected in get_state."""

    from lumen.modes.learn.adapters.storage import LearningStore
    from lumen.modes.learn.plugin import _LearnModeServiceAdapter
    from lumen.modes.learn.policy.mastery import compute_mastery

    store = LearningStore(root=tmp_path)
    adapter = _LearnModeServiceAdapter(agent_loop=object(), store=store)
    await adapter.start("path-1")

    progress = store.load("path-1")
    progress.mastery_levels["kp1"] = compute_mastery(correctness=[True, True, True, False])
    store.save(progress)

    state = await adapter.get_state("path-1")
    assert "kp1" in state["mastery_levels"]
    assert state["mastery_levels"]["kp1"] >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. handle_turn delegates through the injected agent loop
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_handle_turn_sets_mastery_metadata_and_calls_agent_loop():
    from lumen.modes.learn.plugin import _LearnModeServiceAdapter

    calls: list[tuple[Any, Any, str]] = []

    class FakeAgentLoop:
        async def run(self, *, context, stream, language="en", **config):
            calls.append((context, stream, language))

    adapter = _LearnModeServiceAdapter(agent_loop=FakeAgentLoop())

    from lumen.runtime.context import UnifiedContext
    from lumen.runtime.stream.bus import StreamBus

    ctx = UnifiedContext(session_id="s1", user_message="Hi")
    bus = StreamBus()
    await adapter.handle_turn(ctx, bus)

    assert ctx.metadata.get("mastery_mode") is True
    assert ctx.metadata.get("mastery_path_id") == "s1"
    assert len(calls) == 1
    assert calls[0][0] is ctx
    assert calls[0][1] is bus
    assert calls[0][2] == "en"


# 6b. A Learn turn mounts the goal's knowledge space so the tutor can teach
# from the material already imported into it (fix: "没有可用附件文件").
# The material lives in the KB the goal was created from, not in the chat
# composer — bind it to ``context.knowledge_bases`` on first-time turns.


class TestHandleTurnMountsGoalSource:
    def _adapter(self, *, store, knowledge_sources=None):
        from lumen.modes.learn.plugin import _LearnModeServiceAdapter

        calls: list[Any] = []

        class FakeAgentLoop:
            async def run(self, *, context, stream, language="en", **config):
                calls.append(context)

        return _LearnModeServiceAdapter(
            agent_loop=FakeAgentLoop(),
            store=store,
            knowledge_sources=knowledge_sources,
        ), calls

    def _context(self, path_id: str):
        from lumen.runtime.context import UnifiedContext

        return UnifiedContext(
            session_id="s1",
            user_message="继续学习「001.md」",
            metadata={"mastery_path_id": path_id},
        )

    @pytest.mark.asyncio
    async def test_explicit_source_kb_is_mounted(self, tmp_path):
        from lumen.modes.learn.adapters.storage import LearningStore
        from lumen.modes.learn.domain.models import LearningProgress

        store = LearningStore(root=tmp_path)
        progress = LearningProgress(book_id="g1", goal_name="001.md", source_kb="资料库")
        store.save(progress)

        adapter, _ = self._adapter(store=store)
        from lumen.runtime.stream.bus import StreamBus

        ctx = self._context("g1")
        await adapter.handle_turn(ctx, StreamBus())
        assert ctx.knowledge_bases == ["资料库"]

    @pytest.mark.asyncio
    async def test_legacy_goal_discovered_by_name(self, tmp_path, monkeypatch):
        from lumen.modes.learn.adapters.storage import LearningStore
        from lumen.modes.learn.domain.models import LearningProgress

        store = LearningStore(root=tmp_path)
        # Pre-binding goals have no source_kb; the fallback matches the goal
        # name against knowledge-space document names.
        store.save(LearningProgress(book_id="g2", goal_name="001.md"))

        class FakeSources:
            def list_knowledge_bases(self):
                return ["资料库"]

        monkeypatch.setattr(
            "lumen.shared._util.user.resolve_kb_manifest",
            lambda kb, **kw: type("M", (), {"matched": 1})(),
        )

        adapter, _ = self._adapter(store=store, knowledge_sources=FakeSources())
        from lumen.runtime.stream.bus import StreamBus

        ctx = self._context("g2")
        await adapter.handle_turn(ctx, StreamBus())
        assert ctx.knowledge_bases == ["资料库"]

    @pytest.mark.asyncio
    async def test_no_matching_material_leaves_kbs_unchanged(self, tmp_path, monkeypatch):
        from lumen.modes.learn.adapters.storage import LearningStore
        from lumen.modes.learn.domain.models import LearningProgress

        store = LearningStore(root=tmp_path)
        store.save(LearningProgress(book_id="g3", goal_name="no-such-file"))

        class FakeSources:
            def list_knowledge_bases(self):
                return ["资料库"]

        monkeypatch.setattr(
            "lumen.shared._util.user.resolve_kb_manifest",
            lambda kb, **kw: type("M", (), {"matched": 0})(),
        )

        adapter, _ = self._adapter(store=store, knowledge_sources=FakeSources())
        from lumen.runtime.stream.bus import StreamBus

        ctx = self._context("g3")
        await adapter.handle_turn(ctx, StreamBus())
        assert ctx.knowledge_bases == []

    @pytest.mark.asyncio
    async def test_stale_source_kb_is_not_mounted(self, tmp_path):
        from lumen.modes.learn.adapters.storage import LearningStore
        from lumen.modes.learn.domain.models import LearningProgress

        store = LearningStore(root=tmp_path)
        store.save(LearningProgress(book_id="g4", goal_name="001.md", source_kb="已删除的库"))

        class FakeSources:
            def list_knowledge_bases(self):
                return ["资料库"]

        adapter, _ = self._adapter(store=store, knowledge_sources=FakeSources())
        from lumen.runtime.stream.bus import StreamBus

        ctx = self._context("g4")
        await adapter.handle_turn(ctx, StreamBus())
        assert ctx.knowledge_bases == []

    @pytest.mark.asyncio
    async def test_missing_progress_does_not_break_turn(self, tmp_path):
        from lumen.modes.learn.adapters.storage import LearningStore

        adapter, _ = self._adapter(store=LearningStore(root=tmp_path))
        from lumen.runtime.stream.bus import StreamBus

        ctx = self._context("missing")
        await adapter.handle_turn(ctx, StreamBus())
        assert ctx.knowledge_bases == []


# ═══════════════════════════════════════════════════════════════════════════
# 7. binding replaceability still holds in the full profile
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_learn_profile_uses_fake_llm_and_fake_retrieval():
    root = await Bootstrap(profile=LEARN_PROFILE).boot(LEARN_PLUGINS)
    from tests.kernel.fakes import FakeLLMService, FakeRetrievalService

    assert isinstance(root.require("runtime.llm"), FakeLLMService)
    assert isinstance(root.require("knowledge.retrieval"), FakeRetrievalService)
    await root.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# 8. dispose removes mode.learn
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dispose_removes_mode_learn():
    root = await Bootstrap(profile=LEARN_PROFILE).boot(LEARN_PLUGINS)
    await root.dispose()
    with pytest.raises(LookupError):
        root.require("mode.learn")


# ═══════════════════════════════════════════════════════════════════════════
# 9. setup failure rolls back
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_setup_failure_rolls_back():
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

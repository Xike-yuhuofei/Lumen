"""A/B bake-off profiles (Phase 5.5) — legacy vs LangChain agent loop.

Both profiles boot the exact same Runtime / Shared / mode.learn set and
differ ONLY in the ``runtime.agent_loop`` provider.  This isolates the
comparison to the agent loop itself:

    profile.agent_loop_legacy     → AgentLoopPlugin          (runtime.agent_loop)
    profile.agent_loop_langchain  → LangChainAgentLoopPlugin (agent_loop.langchain)
"""

from __future__ import annotations

from lumen.agent_loop_langchain import LangChainAgentLoopPlugin
from lumen.kernel import Profile
from lumen.modes.learn import ModeLearnPlugin
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

#: The shared (non-agent-loop) plugin set — identical for both profiles.
_SHARED_RUNTIME = [
    SessionPlugin(),
    PromptPlugin(),
    ToolPlugin(),
    LLMPlugin(),
    AgentPlugin(),
    KnowledgeSourcesPlugin(),
    KnowledgeRetrievalPlugin(),
    KnowledgeParsingPlugin(),
    MemoryPlugin(),
    NotebookPlugin(),
    RenderingPlugin(),
    ModeLearnPlugin(),
]

#: Legacy agent loop profile — AgentLoopPlugin provides runtime.agent_loop.
AGENT_LOOP_LEGACY_PLUGINS = [*_SHARED_RUNTIME, AgentLoopPlugin()]
AGENT_LOOP_LEGACY_PROFILE = Profile(
    manifests=[p.manifest for p in AGENT_LOOP_LEGACY_PLUGINS],
)

#: LangChain agent loop profile — LangChainAgentLoopPlugin provides
#: runtime.agent_loop via create_react_agent + LangGraph.
AGENT_LOOP_LANGCHAIN_PLUGINS = [*_SHARED_RUNTIME, LangChainAgentLoopPlugin()]
AGENT_LOOP_LANGCHAIN_PROFILE = Profile(
    manifests=[p.manifest for p in AGENT_LOOP_LANGCHAIN_PLUGINS],
)


def non_agent_loop_plugin_ids() -> set[str]:
    """Plugin ids that are identical across both A/B profiles (sanity check)."""
    legacy_ids = {p.manifest.id for p in AGENT_LOOP_LEGACY_PLUGINS}
    langchain_ids = {p.manifest.id for p in AGENT_LOOP_LANGCHAIN_PLUGINS}
    common = legacy_ids & langchain_ids
    assert common == legacy_ids - {"runtime.agent_loop"}
    assert common == langchain_ids - {"agent_loop.langchain"}
    return common

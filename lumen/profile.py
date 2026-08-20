"""Production profile for the Plugin Kernel bootstrap (Phase 5).

This profile defines the canonical set of plugins that constitute the
Lumen runtime in production.  Every plugin uses real providers (not
fakes) and every dependency is declared through ``requires``.

``runtime.agent_loop`` runs on P1 (``agent_loop.langgraph_thin`` / LangGraph
Thin).  The Legacy P0 ``AgentLoopPlugin`` stays registered as a shadowed
provider so a rollback is one ``LUMEN_AGENT_LOOP_PROVIDER=legacy`` env flip.
"""

from __future__ import annotations

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
from lumen.runtime.agent_loop.providers.langgraph_thin import LangGraphThinAgentLoopPlugin
from lumen.shared import (
    KnowledgeParsingPlugin,
    KnowledgeRetrievalPlugin,
    KnowledgeSourcesPlugin,
    MemoryPlugin,
    NotebookPlugin,
    RenderingPlugin,
)

#: The shared (non-agent-loop) plugin set — identical for production and the
#: legacy rollback assembly.
SHARED_PLUGINS = [
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

#: Production plugin set: shared + Legacy (P0, kept for fast rollback) + P1.
#: The binding below elects ``agent_loop.langgraph_thin`` as the Active
#: Provider for ``runtime.agent_loop``; Legacy is shadowed but stays available.
PRODUCTION_PLUGINS = [
    *SHARED_PLUGINS,
    AgentLoopPlugin(),
    LangGraphThinAgentLoopPlugin(),
]

#: Production profile — ``runtime.agent_loop`` → P1 (LangGraph Thin).
PRODUCTION_PROFILE = Profile(
    manifests=[p.manifest for p in PRODUCTION_PLUGINS],
    bindings={"runtime.agent_loop": "agent_loop.langgraph_thin"},
)

#: Legacy-only rollback assembly — pure P0 (no LangGraph Thin plugin).
LEGACY_AGENT_LOOP_PLUGINS = [*SHARED_PLUGINS, AgentLoopPlugin()]
LEGACY_AGENT_LOOP_PROFILE = Profile(
    manifests=[p.manifest for p in LEGACY_AGENT_LOOP_PLUGINS],
)

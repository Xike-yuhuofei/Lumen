"""Production profile for the Plugin Kernel bootstrap (Phase 5).

This profile defines the canonical set of plugins that constitute the
Lumen runtime in production.  Every plugin uses real providers (not
fakes) and every dependency is declared through ``requires``.
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
from lumen.shared import (
    KnowledgeParsingPlugin,
    KnowledgeRetrievalPlugin,
    KnowledgeSourcesPlugin,
    MemoryPlugin,
    NotebookPlugin,
    RenderingPlugin,
)

#: The canonical production plugin set — all real providers.
PRODUCTION_PLUGINS = [
    SessionPlugin(),
    PromptPlugin(),
    ToolPlugin(),
    LLMPlugin(),
    AgentPlugin(),
    AgentLoopPlugin(),
    KnowledgeSourcesPlugin(),
    KnowledgeRetrievalPlugin(),
    KnowledgeParsingPlugin(),
    MemoryPlugin(),
    NotebookPlugin(),
    RenderingPlugin(),
    ModeLearnPlugin(),
]

#: Production profile — no bindings needed because no service has more than
#: one provider in the canonical set.
PRODUCTION_PROFILE = Profile(
    manifests=[p.manifest for p in PRODUCTION_PLUGINS],
)

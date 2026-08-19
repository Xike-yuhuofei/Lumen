"""Dev-environment Active Provider profile (P1 = LangGraph Thin).

This module defines the **dev** assembly: the exact same Runtime / Shared /
mode.learn set as production, with ``runtime.agent_loop`` bound to P1
(``agent_loop.langgraph_thin``) instead of Legacy (P0).

Binding semantics (``lumen.kernel.Profile.bindings``): when several plugins
provide the same service, the binding elects the winner and the losing
providers are not activated.  Both providers ship in the plugin list so a
fallback to P0 is a one-line binding / env-var change — the Legacy
``AgentLoopPlugin`` stays available and untouched.

``PRODUCTION_PROFILE`` is never modified by this module.
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

#: Shared (non-agent-loop) plugins — identical to production.
_DEV_SHARED = [
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

#: Dev plugin set: shared + Legacy (P0, for fast fallback) + P1.
#: The binding below elects P1; P0 is shadowed but remains available.
DEV_PLUGINS = [
    *_DEV_SHARED,
    AgentLoopPlugin(),
    LangGraphThinAgentLoopPlugin(),
]

#: Dev profile — P1 is the Active Provider for ``runtime.agent_loop``.
DEV_PROFILE = Profile(
    manifests=[p.manifest for p in DEV_PLUGINS],
    bindings={"runtime.agent_loop": "agent_loop.langgraph_thin"},
)

"""LangChain agent loop provider — experimental A/B runtime.

``runtime.agent_loop`` backed by ``create_react_agent`` + LangGraph.  NOT the
production default (Phase 6B1 keeps the Legacy provider); switchable via
profile binding ``{"runtime.agent_loop": "agent_loop.langchain"}``.
"""

from lumen.runtime.agent_loop.providers.langchain.plugin import (
    LangChainAgentLoopPlugin,
    _LangChainAgentLoopAdapter,
)

__all__ = [
    "LangChainAgentLoopPlugin",
    "_LangChainAgentLoopAdapter",
]

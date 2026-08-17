"""Deprecated compatibility facade — see ``lumen.runtime.agent_loop.providers.langchain``.

The LangChain ``runtime.agent_loop`` provider is owned by
``lumen/runtime/agent_loop/providers/langchain/`` since Phase 6B1; this package
only re-exports it for the A/B bake-off harness.
"""
from lumen.runtime.agent_loop.providers.langchain import (
    LangChainAgentLoopPlugin,
    _LangChainAgentLoopAdapter,
)

__all__ = [
    "LangChainAgentLoopPlugin",
    "_LangChainAgentLoopAdapter",
]

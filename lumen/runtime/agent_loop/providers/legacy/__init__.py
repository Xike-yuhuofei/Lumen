"""Legacy agent loop provider — the production ``runtime.agent_loop``.

Composes the agent pipeline factory (``runtime.agent``) and the agent loop
runner (``runtime.agent_loop``) from the existing ``deeptutor`` chat agents.
This stays the Production Agent Loop default (Phase 6B1 keeps Legacy).
"""
from lumen.runtime.agent_loop.providers.legacy.agent import (
    AgentPlugin,
    _AgentServiceAdapter,
)
from lumen.runtime.agent_loop.providers.legacy.plugin import (
    AgentLoopPlugin,
    _AgentLoopServiceAdapter,
)

__all__ = [
    "AgentPlugin",
    "AgentLoopPlugin",
    "_AgentServiceAdapter",
    "_AgentLoopServiceAdapter",
]

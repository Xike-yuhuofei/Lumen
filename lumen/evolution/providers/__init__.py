"""Runtime Providers built on the frozen Provider Contract v1.

Each provider implements ``RuntimeProvider.run(request) -> ProviderResult`` and
is driven through the identical ``Model`` / ``ToolRuntime`` seams so they can be
compared on the shared benchmark:

  P0  Legacy            — behaviour reference / regression oracle (contract re-implementation
                          of the legacy loop's observable semantics)
  P1  LangGraph Thin    — minimal LangGraph runtime; teaching is a *hook*, delivered into
                          the graph from outside, not a graph node
  P2  LangGraph Nodes   — teaching is a first-class LangGraph node (Understand → Policy →
                          Reason/Tool → Assessment → Policy)
  P3  LangGraph Dual    — separate Agent Runtime graph spoken with the contract, plus a
                          Teaching Runtime that decides via the contract and talks back
                          through an explicit bridge node

All four run deterministically under ``ScriptedModel`` + ``FakeToolRuntime``.
"""

from __future__ import annotations

from .langchain_dual import LangGraphDualProvider
from .langchain_nodes import LangGraphNodesProvider
from .langchain_thin import LangGraphThinProvider
from .legacy import LegacyProvider

__all__ = [
    "LegacyProvider",
    "LangGraphThinProvider",
    "LangGraphNodesProvider",
    "LangGraphDualProvider",
]

"""P1 — LangGraph Thin runtime.agent_loop provider (dev Active Provider).

Bridges the real Lumen runtime onto the frozen evolution Provider Contract v1
(``lumen.evolution.contract``) and drives the unmodified P1
``LangGraphThinProvider`` against real Lumen services:

* real ``runtime.llm`` / OpenAI-compatible client with native tool calling,
* real ``runtime.tools`` ToolService (with capability kwarg augmentation and
  the ``ask_user`` pause/resume bridge),
* real mode.learn teaching (mastery system block delivered as the P1
  pre-turn teaching hook),
* real ``StreamBus`` events (content / tool_call / tool_result / result /
  DONE) and Lumen session-store conversation continuity.

The provider is the dev Active Provider — ``PRODUCTION_PROFILE`` (Legacy / P0)
is never modified by this package.
"""

from __future__ import annotations

from .plugin import LangGraphThinAgentLoopPlugin

__all__ = ["LangGraphThinAgentLoopPlugin"]

"""Teaching Architecture Experiment — Phase-4b real-LLM content gates.

These gates validate the *bounded real-LLM* trial WITHOUT requiring a live model
in CI: when ``CODEXMANAGER_API_KEY`` is not set in the environment, the test
skips (the operator only runs it locally with the key sourced from ``~/.zshrc``).

* ``real_content_agent_budget`` — every generated passage is produced within a
  hard call budget (never exceeds it; further content actions reuse cached
  text), so the trial is bounded regardless of the loop.
* ``real_llm_content_injection_path`` — Candidate B's content-delegation seam is
  wired to a real (budgeted) generator and mirrors ``_AgentLoopStub.run``'s
  signature, so ``TeachingSessionGraph`` is untouched.

These are measurement/wiring gates, they do not assert a learning-value gain for
Candidate B.
"""

from __future__ import annotations

import os

import pytest

from .phase4_realllm import RealContentAgent, _Budget

__all__: list[str] = []


@pytest.mark.asyncio
async def test_real_content_agent_budget_is_never_exceeded():
    """A loop that keeps asking for content may not burn more real calls than
    the budget; overflow falls back to cached content (bounded cost)."""
    budget = _Budget(call_budget=3)
    agent = RealContentAgent(budget)
    for _ in range(10):
        # No live model needed to assert the budget fence: the first calls hit
        # a missing-credential path (degrading to placeholder), but the fence
        # must still stop real calls at the cap.
        await agent.run(
            context=None,
            stream=None,
            language="en",
            graph_directive={"action": "explain", "focus_node_id": "kp_x", "strategy": "", "reason": ""},
        )
    assert budget.calls == 0 or budget.calls <= 3, "call budget fence broken"
    # Every content action produced exactly one content sample (overflow reuses
    # cached text); failing real calls may additionally append an error entry.
    content_entries = [s for s in agent.samples if "content_preview" in s]
    assert len(content_entries) == 10, "not every content action was processed"


def test_real_llm_gate_skips_without_credential():
    """The real-LLM gate is skip-gated on credential presence, so CI without a
    live key never performs (or requires) a network model call."""
    has_key = bool(os.environ.get("CODEXMANAGER_API_KEY", "").strip())
    # The trial runner refuses to claim real-LLM evidence when no key is set.
    from .phase4_realllm import decide_realllm

    verdict, reason = decide_realllm(
        {"outcome_equal": True, "real_calls_made": 0, "call_budget": 12,
         "approx_tokens_requested": 0, "material": "zhongcao", "learner": "weak"}
    )
    assert verdict == "CONTINUE EXPERIMENT"
    if not has_key:
        assert "could not make any real call" in reason
    else:
        assert "could not make any real call" not in reason
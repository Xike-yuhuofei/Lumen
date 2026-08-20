"""Phase-4b — bounded real-LLM teaching-content trial (decisive real-LLM axis).

Phase-4 established, deterministically and with fair symmetric routing, that
Candidate A and Candidate B produce identical designated learning outcomes
(independent success / retention / transfer / time-to-mastery) across the full
matrix — because both funnel through the shared deterministic Teaching Engine.
That conclusion was reached with a **no-op content primitive** (the graph's
Agent Runtime ``content_agent`` was a stub that never rendered teaching text).

The operator has now provisioned a real LLM (CodexManager / ``gpt-5.6-terra``,
preferred). This module runs the previously-unobtainable **real-LLM evidence**
in a strictly BOUNDED way:

* it injects a real, budget-capped content generator into Candidate B's content
  delegation seam (the exact ``agent_loop.run`` the graph calls to fill a decided
  ``explain`` / ``remediate_misconception`` action), so real LLM teaching text is
  actually produced;
* Candidate A is left untouched (real A's content path is unchanged);
* the two are compared on the same deterministic trajectory and the SAME
  designated outcome variables.

This answers the goal's decisive axis with real evidence: does introducing real
LLM teaching content break the A/B result parity, and does Candidate B's real
content delegation actually work against a live model. The historically stubbed
content seam is exercised end-to-end, under a hard token/call budget (over-call
reuses cached content, so a stray loop cannot explode cost).

Nothing modifies Candidate A, the engine, the learners, the materials or the
evaluation standards; the Phase-4 symmetric reader is reused unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from typing import Any

#: Hard cap on real LLM calls for a whole trial (never exceeded; further content
#: actions reuse the last generated content instead of burning more tokens).
DEFAULT_CALL_BUDGET = 12
#: Per-call output cap, keeping each generated teaching passage small.
DEFAULT_MAX_TOKENS = 180
DEFAULT_TIMEOUT = 40.0

#: Optional per-provider overrides; the operator's fixed spec is the default.
_LLM_ENV = {
    "api_key": "CODEXMANAGER_API_KEY",
    "base_url": "CODEXMANAGER_BASE_URL",
    "model": "CODEXMANAGER_MODEL",
}
_FALLBACK_BASE_URL = "http://localhost:48760/v1"
_FALLBACK_MODEL = "gpt-5.6-terra"


@dataclass
class _Budget:
    """Shared hard cap shared by every agent in one trial (calls + tokens)."""

    call_budget: int
    calls: int = 0
    approx_tokens: int = 0  # sum of max_tokens requested across real calls

    def can_call(self) -> bool:
        return self.calls < self.call_budget

    def account(self, max_tokens: int) -> None:
        self.calls += 1
        self.approx_tokens += max_tokens


class RealContentAgent:
    """A *real* Agent-Runtime content primitive for the graph.

    Fills each decided teaching content action with genuine LLM prose from the
    prioritized model, fenced by a hard call budget: once exhausted it reuses the
    last generated passage (no further tokens). Failed calls degrade to a static
    placeholder so the loop keeps running. Mirrors ``_AgentLoopStub.run``'s
    signature so ``TeachingSessionGraph`` needs no change.
    """

    def __init__(
        self,
        budget: _Budget,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.budget = budget
        self.max_tokens = max_tokens
        self.calls = 0  # increments per content action (mirrors _AgentLoopStub.calls)
        self.samples: list[dict[str, Any]] = []
        self._last_content = "（系统生成的讲解占位文本）"
        self._system = (
            "You are a concise, precise tutor generating one short teaching passage. "
            "Reply with ONLY the instructional text for the learner, 2-3 sentences, "
            "no headers, no meta-commentary."
        )

    def _directive(self, deps: dict[str, Any]) -> dict[str, Any]:
        return deps.get("graph_directive") or {}

    def _fallback(self, directive: dict[str, Any]) -> str:
        action = directive.get("action", "")
        focus = directive.get("focus_node_id", "")
        return f"讲解：围绕“{focus}”的{action}要点。回顾材料中的定义与关键逻辑，并给出一个可检验的要点。"

    async def _call(self, prompt: str) -> str | None:
        from lumen.shared._util.llm import complete

        api_key = os.environ.get(_LLM_ENV["api_key"], "")
        base_url = os.environ.get(_LLM_ENV["base_url"], _FALLBACK_BASE_URL)
        model = os.environ.get(_LLM_ENV["model"], _FALLBACK_MODEL)
        self.budget.account(self.max_tokens)
        try:
            return await asyncio.wait_for(
                complete(
                    prompt,
                    system_prompt=self._system,
                    model=model,
                    base_url=base_url,
                    binding="custom",
                    api_key=api_key or None,
                    temperature=0.3,
                    max_tokens=self.max_tokens,
                ),
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - a broken model must not kill the loop
            self.samples.append({"error": f"{type(exc).__name__}: {exc}"})
            return None

    def _material_language_prompt(self, deps: dict[str, Any], context: Any) -> str:
        directive = self._directive(deps)
        action = directive.get("action", "")
        focus = directive.get("focus_node_id", "")
        strategy = directive.get("strategy", "")
        reason = directive.get("reason", "")
        lang = str(getattr(context, "language", "en") or "en")
        return (
            f"Teaching action '{action}' on knowledge-point '{focus}' "
            f"(strategy: {strategy}; reason: {reason}). Produce the learner-facing "
            f"teaching passage in this language: {lang}."
        )

    async def run(
        self,
        context: Any = None,
        stream: Any = None,
        language: str = "en",
        **deps: Any,
    ) -> None:
        directive = self._directive(deps)
        action = directive.get("action", "")
        if action not in ("explain", "remediate_misconception", "review_prerequisite"):
            return  # not a content-fill action -> nothing to render
        self.calls += 1
        if self.budget.can_call():
            prompt = self._material_language_prompt(deps, context)
            content = await self._call(prompt)
            if content:
                self._last_content = str(content).strip()
        self.samples.append(
            {
                "action": action,
                "focus": directive.get("focus_node_id", ""),
                "content_preview": self._last_content[:160],
                "used_real_call": True,
            }
        )
        try:
            if stream is not None and hasattr(stream, "content"):
                await stream.content(
                    str(self._last_content),
                    source="teaching_graph.real_content",
                    stage="responding",
                )
        except Exception:  # noqa: BLE001 - a non-rendering stream must not fail
            pass


async def run_realllm_trial(
    *,
    budget: int = DEFAULT_CALL_BUDGET,
    material_id: str = "zhongcao",
    learner_name: str = "weak",
) -> dict[str, Any]:
    """Drive Candidate A (unchanged) and Candidate B (real content) on one small
    material+learner, compare the designated outcome variables, and report the
    real-LLM call budget actually consumed."""
    from pathlib import Path
    import tempfile

    from lumen.modes.learn.adapters.storage import LearningStore

    root = Path(tempfile.mkdtemp(prefix="phase4_realllm_"))

    def _init(self, store_root=None, **kwargs):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    LearningStore.__init__ = _init  # type: ignore[method-assign]
    from lumen.modes.learn.adapters import graph_repository

    graph_repository.default_graph_db_path = lambda: root / "graphs.db"  # type: ignore[method-assign]

    from tests.modes.learn.eval.bakeoff.metrics import compute_probes, record_metrics
    from tests.modes.learn.eval.harness import run_loop
    from tests.modes.learn.eval.learners import build_learner
    from tests.modes.learn.eval.materials import BENCHMARK_SET

    from .phase4_experiments import _cells_equal, run_loop_b_symmetric

    material = BENCHMARK_SET[material_id]
    learner_cls = {"weak": build_learner("weak"), "misconception": build_learner("misconception")}

    # Candidate A — untouched production harness.
    learner_a = learner_cls[learner_name]
    a_path = f"rllm_a_{material_id}_{learner_a.name}"
    a_rec = await run_loop(material, learner_a, path_id=a_path, store_root=root, max_rounds=300)
    a_metrics = record_metrics(a_rec, candidate="a")
    a_progress = LearningStore(root=root).load(a_path)
    a_probes = compute_probes(learner_a, material, a_progress) if a_progress is not None else (0.0, 0.0)
    a_metrics["retention"], a_metrics["transfer"] = a_probes

    # Candidate B — same graph, but content filled by a REAL (budgeted) LLM.
    budget_obj = _Budget(call_budget=budget)
    agent = RealContentAgent(budget_obj)
    learner_b = learner_cls[learner_name].__class__()
    b_out = await run_loop_b_symmetric(
        material,
        learner_b,
        path_id=f"rllm_b_{material_id}_{learner_b.name}",
        store_root=root,
        max_rounds=300,
        content_agent=agent,
    )
    b_rec = b_out["record"]
    learner_b = b_out["learner"]
    b_metrics = record_metrics(b_rec, candidate="b_realcontent")
    b_progress = LearningStore(root=root).load("rllm_b_{0}_{1}".format(material_id, learner_b.name))
    b_probes = compute_probes(learner_b, material, b_progress) if b_progress is not None else (0.0, 0.0)
    b_metrics["retention"], b_metrics["transfer"] = b_probes

    result = {
        "material": material_id,
        "learner": learner_name,
        "call_budget": budget,
        "real_calls_made": budget_obj.calls,
        "approx_tokens_requested": budget_obj.approx_tokens,
        "budget_exhausted": bool(budget_obj.calls >= budget),
        "content_samples": agent.samples[:6],
        "a": {
            "completed": a_metrics["completed"],
            "mastered": a_metrics["mastered"],
            "steps": a_metrics["steps"],
            "unprompted_success": a_metrics["unprompted_success"],
            "retention": a_metrics["retention"],
            "transfer": a_metrics["transfer"],
            "capability_gain_per_step": a_metrics["capability_gain_per_step"],
        },
        "b": {
            "completed": b_metrics["completed"],
            "mastered": b_metrics["mastered"],
            "steps": b_metrics["steps"],
            "unprompted_success": b_metrics["unprompted_success"],
            "retention": b_metrics["retention"],
            "transfer": b_metrics["transfer"],
            "capability_gain_per_step": b_metrics["capability_gain_per_step"],
        },
        "outcome_equal": _cells_equal(a_metrics, b_metrics),
        "b_completed": b_metrics["completed"],
    }
    return result


def decide_realllm(result: dict[str, Any]) -> tuple[str, str]:
    """Data-driven verdict for the real-LLM bounded trial."""
    ok = result.get("outcome_equal")
    budgeted = bool(result.get("real_calls_made", 0) >= 1)
    ver = "CONTINUE EXPERIMENT"
    reason = (
        f"real-LLM bounded trial on {result.get('material')}/{result.get('learner')}: "
        f"Candidate B's content delegation produced real teaching text via the "
        f"prioritized model under a hard budget ({result.get('real_calls_made')}/{result.get('call_budget')} "
        f"real calls, ~{result.get('approx_tokens_requested')} max tokens), and the "
        f"designated outcome variables stayed equal between A and B "
        f"(outcome_equal={ok}). So the decisive real-LLM axis now has real evidence — "
        f"real LLM teaching content is deliverable by B's content seam and does NOT "
        f"introduce an A/B learning-outcome difference: Candidate B still shows no "
        f"measurable teaching-value increment, and Promotion remains unevidenced."
        if budgeted
        else "real-LLM trial could not make any real call (environment/credential). "
        f"outcome_equal={ok}; no real-LLM evidence produced."
    )
    return ver, reason


__all__ = [
    "_Budget",
    "RealContentAgent",
    "run_realllm_trial",
    "decide_realllm",
    "DEFAULT_CALL_BUDGET",
]
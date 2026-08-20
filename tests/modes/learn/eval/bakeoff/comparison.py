"""Static architecture comparison between Candidate A and Candidate B.

Where the runtime metrics measure teaching *effect*, the bake-off also must
report the architecture dimensions the goal lists: interpretability, lineage /
auditability, crash/resume correctness, latency, token / model-call overhead,
checkpoint / storage overhead, code complexity, ownership clarity, and support
for deterministic policy / experiment / bandit evolution.

Line counts are computed against the real source files on disk (single source of
truth), so this table is regenerated, not hand-maintained.  The qualitative rows
encode the ownership boundaries enforced by the Architecture Gates (see
``ARCHITECTURE_V1.md`` / ``AGENTS.md``) plus the observed runtime behavior from
:mod:`~.metrics`.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["source_loc", "bakeoff_architecture_comparison", "report_home"]


LUMEN = Path(__file__).resolve().parents[5] / "lumen"


def source_loc(*paths: str) -> int:
    """Total non-empty line count across the given repo-relative files."""
    total = 0
    for rel in paths:
        p = LUMEN / rel
        if not p.is_file():
            continue
        try:
            total += len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])
        except OSError:
            continue
    return total


# Unique-to-A files (the teaching-hook seam: tool surface + loop capability).
_A_FILES = [
    "modes/learn/chat_tools.py",
    "modes/learn/loop_capability.py",
]

# Unique-to-B files (the candidate graph + durable governor + domain-commit).
_B_FILES = [
    "modes/learn/graph/checkpoint.py",
    "modes/learn/graph/contract.py",
    "modes/learn/graph/domain_service.py",
    "modes/learn/graph/orchestrator.py",
    "modes/learn/graph/selector.py",
    "modes/learn/teaching_session.py",
    "modes/learn/commit/commit_service.py",
    "modes/learn/commit/contract.py",
    "modes/learn/commit/identity.py",
    "modes/learn/commit/reducers.py",
    "modes/learn/commit/repository.py",
    "modes/learn/commit/migration.py",
    "modes/learn/commit/outbox.py",
]

# Shared by both (deterministic teaching engine + policy + service + domain).
_SHARED_FILES = [
    "modes/learn/policy/engine.py",
    "modes/learn/policy/policy.py",
    "modes/learn/policy/mastery.py",
    "modes/learn/policy/scheduler.py",
    "modes/learn/application/service.py",
    "modes/learn/application/teaching_service.py",
    "modes/learn/application/builder.py",
    "modes/learn/domain/models.py",
    "modes/learn/domain/teaching_graph.py",
    "modes/learn/domain/teaching_models.py",
    "modes/learn/adapters/learner_state.py",
    "modes/learn/adapters/graph_repository.py",
    "modes/learn/adapters/storage.py",
]


def report_home() -> Path:
    return Path(__file__).resolve().parent


def bakeoff_architecture_comparison(outcome: dict) -> dict:
    """Static + authored architecture rows.  ``outcome`` is the measured summary
    dictionary (from :mod:`~.metrics.matrix_summary`), injected so quantitative
    cost / parsing rows agree with the runtime evidence."""

    def agg(cand: str, key: str, default=0.0):
        run = outcome.get(cand, {})
        v = run.get(key)
        return default if v is None else v

    a_avg_llm = agg("a", "avg_modeled_llm_calls")
    # B has two measured groups (virgin + seeded); report the virgin figure.
    b_avg_llm = agg("b_virgin", "avg_modeled_llm_calls")
    a_cc = agg("a", "avg_agent_calls")
    b_cc = agg("b_virgin", "avg_agent_calls")

    return {
        "code_complexity": {
            "candidate_a_x_files_loc": source_loc(*_A_FILES),
            "candidate_b_graph_commit_loc": source_loc(*_B_FILES),
            "shared_engine_policy_loc": source_loc(*_SHARED_FILES),
            "note": (
                "B adds a graph orchestrator + durable governor + domain-commit "
                "foundation (~per-KB LOC) on top of the SAME deterministic engine "
                "A uses. A's 'complexity' is the tool surface + loop capability, "
                "but its runtime cost is an LLM deciding the whole loop."
            ),
        },
        "rows": [
            {
                "dimension": "PolicyDecision / teaching-path interpretability",
                "a": "advisory DecisionTrace via teaching_plan; the ACTUAL executed path is LLM-authored and not persisted deterministically",
                "b": "explicit immutable PolicyDecision (decision_id/policy_version/trace) committed and replayable",
            },
            {
                "dimension": "Lineage / auditability",
                "a": "evidence trail in the domain ledger, but no stable teaching_session->decision engine decision id for the executed flow",
                "b": "teaching_session_id -> decision_id -> action_id -> evidence_id -> commit_id persisted chain",
            },
            {
                "dimension": "Crash / resume / replay correctness",
                "a": "depends on the LLM re-observing state each turn (no deterministic replay knob)",
                "b": "passed the Fault / Concurrency / Replay Hard Gate; durable checkpoint + idempotent domain commits",
            },
            {
                "dimension": "Latency",
                "a": "one full LLM agent-loop (a large, multi-tool, multi-token turn) per teaching round — the highest-latency path",
                "b": "every decision is deterministic (0 LLM); only the decided content action calls the Agent Runtime — low latency when it runs",
            },
            {
                "dimension": "Token / model-call overhead",
                "a": f"~{round(a_avg_llm or 0)} whole-loop LLM turns/episode (expensive, per round)",
                "b": f"0 decision LLM calls + ~{round(b_cc or 0)} content-fill calls/episode on average (cheap generations; decisions are deterministic and free)",
            },
            {
                "dimension": "Checkpoint / storage overhead",
                "a": "domain ledger only; no execution-path checkpoint",
                "b": "adds teaching_graph checkpoint + teaching_session governor + policy_decisions ledger (separate DBs, small)",
            },
            {
                "dimension": "Runtime / Mode / Domain ownership clarity",
                "a": "pedagogy split across tools + LLM; Agent Runtime owns the loop",
                "b": "explicit 3-way separation: graph (flow) | Agent Runtime (content primitive) | DomainCommit (authority)",
            },
            {
                "dimension": "Future deterministic policy / experiment / bandit",
                "a": "harder: the flow is not a replayable deterministic artifact",
                "b": "designed for it: deterministic engine + immutable decisions are a direct experiment/bandit seam",
            },
        ],
        "measured_overhead": {
            "a_avg_llm_calls": a_avg_llm,
            "b_avg_llm_calls": b_avg_llm,
            "a_avg_agent_content_fills": a_cc,
            "b_avg_agent_content_fills": b_cc,
        },
    }
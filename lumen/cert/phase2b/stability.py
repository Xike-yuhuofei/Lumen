"""Phase 2B — misconception scenarios, trial aggregation and stability decision.

Canonical home: ``lumen/cert/phase2b``.

Reuses the Phase 2A scenario registry and candidate builder wholesale. Phase 2B
adds one more misconception-correction scenario (base-rate neglect) so the
``socratic-questions`` vs Frozen Baseline comparison spans
**multiple related-but-different** misconception scenarios, and provides the
trial-level aggregation + stability decision that answers *"is a single-run edge
real, or single-trajectory / evaluator noise?"*.
"""

from __future__ import annotations

import statistics
from typing import Any

from ..phase2.compare import strip_tool_io  # noqa: F401  (re-exported for callers)
from ..phase2.scenarios import (
    BASELINE_STRATEGY_ID,
    SCENARIOS,
    build_candidate,
    load_real_base_prompt,  # noqa: F401  (re-exported for run.py / finalize.py)
)

#: The strategy under stability study in Phase 2B.
SOCRATIC_STRATEGY_ID = "socratic-questions"

#: Phase 2B trials are run for these strategies only (Frozen Baseline + the
#: candidate under study). Order: baseline first.
PHASE2B_STRATEGIES = [BASELINE_STRATEGY_ID, SOCRATIC_STRATEGY_ID]

#: Scenario C — misconception-correction ripe but distinct from the two Phase 2A
#: scenarios (base-rate neglect / conditional probability).
SCENARIO_BASE_RATE: dict[str, Any] = {
    "id": "base-rate-neglect",
    "tutor_config": {
        "subject": "Base rates and conditional probability",
        "goal": "Understand base-rate neglect and how to correctly compute a "
                "posterior from base rate, sensitivity and false-positive rate.",
        "knowledge_points": [
            "the base rate of an event in the population is the prior",
            "a positive test does not imply a high probability of the condition "
                "(sensitivity vs positive predictive value)",
            "Bayes' rule weighs the base rate against the evidence",
            "rarer conditions are more likely to be false positives",
        ],
        "learner_profile": "a bright but overconfident adult who neglects the base "
            "rate, overweights a striking positive test result, and feels that near-"
            "perfect test accuracy makes false positives unlikely; may assert this "
            "out loud and replies naturally in 1-3 sentences",
        "path_id": "",
    },
}

#: Phase 2B scenario set = Phase 2A misconception scenarios + base-rate neglect.
PHASE2B_SCENARIOS: dict[str, dict[str, Any]] = {
    **SCENARIOS,
    SCENARIO_BASE_RATE["id"]: SCENARIO_BASE_RATE,
}

#: Minimum number of scenario-level "better" outcomes required to consider the
#: candidate stably better (across the multi-scenario comparison).
MIN_SCENARIOS_BETTER = 2

#: Numerically-treatise-as-equal threshold on mean pass-rate delta.
EPS = 1e-9


def build_phase2b_candidate(
    *,
    strategy: str,
    scenario: dict[str, Any],
    base_prompt: str,
) -> Any:
    """Build a candidate reusing the Phase 2A builder (content-digest identity)."""
    return build_candidate(strategy=strategy, scenario=scenario, base_prompt=base_prompt)


def aggregate_trials(cells: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Group cell reports by (scenario, strategy) and aggregate trial statistics.

    ``cells`` is the flat list of episode reports (one per scenario x strategy x
    trial). Returns ``{scenario_id: {strategy_id: stats}}`` where ``stats``
    carries mean/std pass rate, mean confidence, the individual trial pass rates
    and per-trial episode ids (traceability).
    """
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for c in cells:
        by.setdefault((c["scenario_id"], c["strategy_id"]), []).append(c)

    agg: dict[str, dict[str, dict[str, Any]]] = {}
    for (scen, strat), reps in by.items():
        prs = [float(r.get("pass_rate") or 0.0) for r in reps]
        confs = [float(r.get("mean_confidence") or 0.0) for r in reps if r.get("mean_confidence")]
        std = statistics.stdev(prs) if len(prs) > 1 else 0.0
        agg.setdefault(scen, {})[strat] = {
            "n_trials": len(reps),
            "mean_pass_rate": round(statistics.fmean(prs), 4) if prs else 0.0,
            "std_pass_rate": round(std, 4),
            "mean_confidence": round(statistics.fmean(confs), 4) if confs else 0.0,
            "pass_rates": [round(p, 4) for p in prs],
            "trials": [
                {
                    "pass_rate": round(float(r.get("pass_rate") or 0.0), 4),
                    "all_pass": bool(r.get("all_pass")),
                    "episode_status": r.get("episode_status"),
                    "episode_id": r.get("episode_id"),
                    "effective_candidate_id": r.get("effective_candidate_id"),
                    "no_go_total": int(r.get("no_go_total") or 0),
                }
                for r in reps
            ],
        }
    return agg


def _robust_to_best_trial(prs: list[float], base_mean: float) -> bool:
    """True if the candidate's mean stays above ``base_mean`` after dropping its
    best (most favourable) trial — i.e. the advantage is not one lucky episode."""
    if len(prs) < 2:
        return False  # need repetition to rule out a single swing
    trimmed = [p for p in prs]
    trimmed.remove(max(trimmed))
    return statistics.fmean(trimmed) > base_mean + EPS


def stability_decide(
    agg: dict[str, dict[str, dict[str, Any]]],
    *,
    gate: dict[str, Any] | None = None,
    min_scenarios: int = MIN_SCENARIOS_BETTER,
) -> dict[str, Any]:
    """Decide whether ``socratic-questions`` is stably better than the Baseline.

    Per scenario, compares candidate mean pass rate vs baseline mean. A candidate
    is "better" in a scenario when its mean beats baseline AND remains above the
    baseline mean after dropping its own best trial (robust to a single swing).

    PROMOTE requires:
    1. never worse (at the mean level) in any compared scenario;
    2. better (robustly) in at least ``min_scenarios`` scenarios;
    3. candidate global mean pass-rate > baseline global mean pass-rate;
    4. promotion gates (replay / regression / phase1 certification) all pass.
    """
    comparisons: dict[str, dict[str, Any]] = {}
    better = worse = equal = 0
    for scen, st in agg.items():
        base = st.get(BASELINE_STRATEGY_ID)
        soc = st.get(SOCRATIC_STRATEGY_ID)
        if base is None or soc is None:
            continue
        delta = soc["mean_pass_rate"] - base["mean_pass_rate"]
        robust = _robust_to_best_trial(soc["pass_rates"], base["mean_pass_rate"])
        if delta > EPS:
            verdict = "better" if robust else "better_unstable"
        elif delta < -EPS:
            verdict = "worse"
        else:
            verdict = "equal"
        comparisons[scen] = {
            "verdict": verdict,
            "delta_mean_pass_rate": round(delta, 4),
            "socratic": soc,
            "baseline": base,
            "robust_to_best_trial": robust,
        }
        if verdict == "better":
            better += 1
        elif verdict == "worse":
            worse += 1
        else:
            equal += 1

    base_pairs = []
    soc_pairs = []
    for c in comparisons.values():
        base_pairs.append((c["baseline"]["mean_pass_rate"], c["baseline"]["n_trials"]))
        soc_pairs.append((c["socratic"]["mean_pass_rate"], c["socratic"]["n_trials"]))
    base_global = _weighted_mean(base_pairs)
    soc_global = _weighted_mean(soc_pairs)
    gates_ok = bool(
        gate
        and gate.get("replay_pass")
        and gate.get("regression_pass")
        and gate.get("phase1_certification_pass")
    )
    never_worse = worse == 0
    promote = bool(
        better >= min_scenarios and never_worse and soc_global > base_global + EPS and gates_ok
    )
    return {
        "final": "PROMOTE CANDIDATE" if promote else "KEEP BASELINE / CONTINUE EXPERIMENT",
        "decision": "PROMOTE CANDIDATE" if promote else "KEEP BASELINE / CONTINUE EXPERIMENT",
        "promoted_candidates": [SOCRATIC_STRATEGY_ID] if promote else [],
        "better_scenarios": better,
        "worse_scenarios": worse,
        "equal_scenarios": equal,
        "never_worse_pass": never_worse,
        "global_mean_pass_rate": {"baseline": round(base_global, 4), "socratic": round(soc_global, 4)},
        "gates": gate or {},
        "gates_pass": gates_ok,
        "per_scenario": comparisons,
        "min_scenarios": min_scenarios,
    }


def _weighted_mean(pairs: list[tuple[float, int]]) -> float:
    """Mean of per-scenario means weighted by the number of trials in each."""
    total_n = sum(n for _p, n in pairs)
    if not total_n:
        return 0.0
    return statistics.fsum(p * n for p, n in pairs) / total_n


__all__ = [
    "SOCRATIC_STRATEGY_ID",
    "PHASE2B_STRATEGIES",
    "PHASE2B_SCENARIOS",
    "SCENARIO_BASE_RATE",
    "MIN_SCENARIOS_BETTER",
    "strip_tool_io",
    "build_phase2b_candidate",
    "aggregate_trials",
    "stability_decide",
]
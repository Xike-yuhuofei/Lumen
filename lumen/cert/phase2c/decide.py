"""Phase 2C — adaptive-vs-fixed Teaching Strategy promotion decision.

Canonical home: ``lumen/cert/phase2c``.

Decides, from a real multi-trial matrix, whether the **Adaptive Strategy
Selection** arm adds value over *every* single fixed strategy (Frozen Baseline
and fixed ``socratic-questions``), and whether that value genuinely comes *from
selection* rather than by degenerating into one fixed strategy.

PROMOTE ADAPTIVE CANDIDATE requires ALL of:
1. promotion gates pass (replay / regression / phase1 certification);
2. the adaptive arm is **not degenerate** — it actually exercises a mix of
   strategies across turns (dominant-strategy ratio <= threshold and more than
   one distinct inner strategy is ever used);
3. adaptive global (trial-weighted mean) pass-rate beats **both** baseline and
   fixed--socratic globally;
4. adaptive robustly beats the *best* fixed arm in at least ``min_scenarios``
   scenarios (advantage survives dropping the adaptive arm's own best trial);
5. adaptive is **never strictly worse than the Frozen Baseline** in any compared
   scenario (the protected anchor must not regress).

Otherwise the verdict is **KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT**.
"""

from __future__ import annotations

import statistics
from typing import Any

from ..phase2.scenarios import BASELINE_STRATEGY_ID
from .adaptive import (
    ADAPTIVE_STRATEGY_ID,
    AVAILABLE_STRATEGIES,
    strategy_mix,
)

PROMOTE = "PROMOTE ADAPTIVE CANDIDATE"
KEEP = "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"

FIXED_STRATEGIES = [BASELINE_STRATEGY_ID, "socratic-questions"]

#: Dominant-strategy share above which an adaptive arm is considered degenerate
#: (indistinguishable from using that one fixed strategy per turn).
DEGENERATION_RATIO = 0.85

EPS = 1e-9


def _robust_to(fixed_mean: float, pass_rates: list[float]) -> bool:
    """Adaptive advantage survives dropping adaptive's own best trial."""
    if len(pass_rates) < 2:
        return False
    trimmed = list(pass_rates)
    trimmed.remove(max(trimmed))
    return statistics.fmean(trimmed) > fixed_mean + EPS


def aggregate_strategy(
    agg_by_scen: dict[str, dict[str, Any]],
    strategy_id: str,
) -> tuple[float, float]:
    """Return (global trial-weighted mean pass-rate, total trials) for a strategy."""
    pairs: list[tuple[float, int]] = []
    for st in agg_by_scen.values():
        s = st.get(strategy_id)
        if s:
            pairs.append((s["mean_pass_rate"], s["n_trials"]))
    total_n = sum(n for _p, n in pairs)
    if not total_n:
        return 0.0, 0.0
    return statistics.fsum(p * n for p, n in pairs) / total_n, total_n


def decide(
    cells: list[dict[str, Any]],
    *,
    gate: dict[str, Any] | None = None,
    min_scenarios: int = 2,
    degeneracy_ratio: float = DEGENERATION_RATIO,
) -> dict[str, Any]:
    """Decide adaptive promotion across a real (multi-trial) comparison matrix."""
    # ---- aggregate by (scenario, strategy) ----
    by_scen: dict[str, dict[str, dict[str, Any]]] = {}
    by_cell: dict[str, dict[str, Any]] = {}
    for c in cells:
        sid = str(c.get("strategy_id") or "?")
        sid = sid if sid != ADAPTIVE_STRATEGY_ID else ADAPTIVE_STRATEGY_ID
        by_scen.setdefault(c["scenario_id"], {}).setdefault(sid, {"trials": []})
        by_scen[c["scenario_id"]][sid]["trials"].append(c)
        by_cell[c["episode_id"]] = c

    agg: dict[str, dict[str, dict[str, Any]]] = {}
    for scen, st_map in by_scen.items():
        for sid, blk in st_map.items():
            prs = [float(t.get("pass_rate") or 0.0) for t in blk["trials"]]
            std = statistics.stdev(prs) if len(prs) > 1 else 0.0
            confs = [float(t.get("mean_confidence") or 0.0) for t in blk["trials"] if t.get("mean_confidence")]
            block = {
                "n_trials": len(prs),
                "mean_pass_rate": round(statistics.fmean(prs), 4) if prs else 0.0,
                "std_pass_rate": round(std, 4),
                "pass_rates": [round(p, 4) for p in prs],
                "mean_confidence": round(statistics.fmean(confs), 4) if confs else 0.0,
                "trial_ids": [t.get("episode_id") for t in blk["trials"]],
            }
            agg.setdefault(scen, {})[sid] = block

    # ---- global weighted means ----
    globals_ = {
        sid: aggregate_strategy(agg, sid)[0]
        for sid in [BASELINE_STRATEGY_ID, "socratic-questions", ADAPTIVE_STRATEGY_ID]
    }

    # ---- per-scenario comparisons ----
    comparisons: dict[str, dict[str, Any]] = {}
    better_than_best_fixed = worse_than_baseline = 0
    better_baseline = better_socratic = 0
    for scen, st in agg.items():
        base = st.get(BASELINE_STRATEGY_ID)
        soc = st.get("socratic-questions")
        ad = st.get(ADAPTIVE_STRATEGY_ID)
        if ad is None:
            continue
        ad_mean = ad["mean_pass_rate"]
        base_mean = base["mean_pass_rate"] if base else 0.0
        soc_mean = soc["mean_pass_rate"] if soc else 0.0
        best_fixed = max(base_mean, soc_mean)
        robust_best = best_fixed is not None and _robust_to(best_fixed if base or soc else 0.0, ad["pass_rates"]) if (base or soc) else False
        robust_base = base is not None and _robust_to(base_mean, ad["pass_rates"])
        robust_soc = soc is not None and _robust_to(soc_mean, ad["pass_rates"])
        worse_base = base is not None and ad_mean < base_mean - EPS
        comparisons[scen] = {
            "adaptive_mean_pass_rate": ad_mean,
            "baseline_mean_pass_rate": base_mean,
            "socratic_mean_pass_rate": soc_mean,
            "best_fixed_mean_pass_rate": best_fixed,
            "better_than_baseline": bool(ad_mean > base_mean + EPS and robust_base) if base else False,
            "better_than_socratic": bool(ad_mean > soc_mean + EPS and robust_soc) if soc else False,
            "better_than_best_fixed_robust": bool(robust_best and ad_mean > best_fixed + EPS),
            "worse_than_baseline": worse_base,
            "baseline": base,
            "socratic": soc,
            "adaptive": ad,
        }
        if comparisons[scen]["better_than_baseline"]:
            better_baseline += 1
        if comparisons[scen]["better_than_socratic"]:
            better_socratic += 1
        if comparisons[scen]["better_than_best_fixed_robust"]:
            better_than_best_fixed += 1
        if worse_base:
            worse_than_baseline += 1

    # ---- anti-degeneration: strategy mix across all adaptive decisions ----
    adaptive_decisions = [
        d
        for c in cells
        if c.get("strategy_id") == ADAPTIVE_STRATEGY_ID
        for d in (c.get("strategy_decisions") or [])
    ]
    mix = strategy_mix(adaptive_decisions)
    distinct = {s for s in mix.get("by_strategy", {}).keys()}
    degenerate = bool(
        mix["total"] > 0
        and (
            mix["dominant_ratio"] > degeneracy_ratio + EPS
            or len(distinct) < 2
        )
    )

    gates_ok = bool(
        gate
        and gate.get("replay_pass")
        and gate.get("regression_pass")
        and gate.get("phase1_certification_pass")
    )

    ad_global = globals_[ADAPTIVE_STRATEGY_ID]
    base_global = globals_[BASELINE_STRATEGY_ID]
    soc_global = globals_["socratic-questions"]
    beats_both_globally = bool(
        ad_global > base_global + EPS and ad_global > soc_global + EPS
    )

    promote = bool(
        gates_ok
        and not degenerate
        and beats_both_globally
        and better_than_best_fixed >= min_scenarios
        and worse_than_baseline == 0
    )

    return {
        "final": PROMOTE if promote else KEEP,
        "decision": PROMOTE if promote else KEEP,
        "promoted_candidates": [ADAPTIVE_STRATEGY_ID] if promote else [],
        "adaptive_capability": {
            "strategy_ids": list(AVAILABLE_STRATEGIES),
            "selection_policy": (
                "per-turn, from public learner signal: socratic (elicit) on "
                "opening/backchannel, diagnose-first (correct a voiced claim) on "
                "strong-claim utterances, default otherwise"
            ),
        },
        "global_mean_pass_rate": {
            "baseline": round(base_global, 4),
            "socratic-questions": round(soc_global, 4),
            "adaptive": round(ad_global, 4),
        },
        "per_scenario": comparisons,
        "better_than_baseline_scenarios": better_baseline,
        "better_than_socratic_scenarios": better_socratic,
        "better_than_best_fixed_scenarios": better_than_best_fixed,
        "worse_than_baseline_scenarios": worse_than_baseline,
        "strategy_mix": mix,
        "degenerate": degenerate,
        "degeneracy_ratio_threshold": degeneracy_ratio,
        "beats_both_globally": beats_both_globally,
        "gates": gate or {},
        "gates_pass": gates_ok,
        "min_scenarios": min_scenarios,
    }


__all__ = ["decide", "PROMOTE", "KEEP", "DEGENERATION_RATIO", "FIXED_STRATEGIES"]
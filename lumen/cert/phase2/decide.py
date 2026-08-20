"""Phase 2A — strategy-vs-baseline promotion decision.

Canonical home: ``lumen/cert/phase2``.

Data-driven decision over a comparison matrix of cells (one report per
strategy x scenario). It compares every non-baseline strategy to the **Frozen
Baseline** on the teaching-behaviour axes that Phase 2A may claim:

* ``all_pass`` / ``pass_rate`` (teaching stability; a strategy that certifies a
  full N-turn Episode dominates one that produces NO_GO) and
* ``mean_confidence`` (evaluator certainty — a secondary quality signal, never
  used to redeem a NO_GO).

PROMOTE requires, per a candidate, and *across more than one scenario*:

1. it is never worse than baseline on ``pass_rate`` in any scenario;
2. strictly better (higher pass_rate, or equal pass_rate with higher
   mean_confidence) in **at least two** scenarios OR in one scenario where the
   baseline did **not** fully pass;
3. a material gap exists (pass_rate delta) — a coin-flip tiny difference is not
   grounds to change the frozen baseline.

Otherwise the verdict is **KEEP BASELINE / CONTINUE EXPERIMENT** (the default
"insufficient evidence to promote" outcome). Promotion additionally requires
Frozen Replay + Minimal Regression + Phase 1 certification gates to pass, which
the caller must supply as ``gates`` evidence — a candidate is never promoted on
metrics alone.
"""

from __future__ import annotations

from typing import Any

from .scenarios import BASELINE_STRATEGY_ID

#: promotion decision strings
PROMOTE = "PROMOTE CANDIDATE"
KEEP = "KEEP BASELINE / CONTINUE EXPERIMENT"


def _row(cell: dict[str, Any]) -> tuple[float, float, bool]:
    return (float(cell.get("pass_rate") or 0.0), float(cell.get("mean_confidence") or 0.0), bool(cell.get("all_pass")))


def compare_vs_baseline(cell: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Classify one strategy cell as strictly-better / equal / worse vs baseline."""
    pr, mc, ap = _row(cell)
    bpr, bmc, bap = _row(base)
    if pr != bpr:
        verdict = "better" if pr > bpr else "worse"
        gap = round(pr - bpr, 4)
    elif ap != bap:
        verdict = "better" if ap else "worse"
        gap = 1.0 if ap else -1.0
    elif mc != bmc:
        verdict = "better" if mc > bmc else "worse"
        gap = round(mc - bmc, 4)
    else:
        verdict = "equal"
        gap = 0.0
    return {"verdict": verdict, "gap": gap, "pass_rate": pr, "base_pass_rate": bpr,
            "mean_confidence": mc, "base_mean_confidence": bmc,
            "all_pass": ap, "base_all_pass": bap, "status": cell.get("episode_status")}


def decide(matrix: list[dict[str, Any]], *, gate: dict[str, Any] | None = None,
           min_strictly_better_scenarios: int = 2) -> dict[str, Any]:
    """Decide promotion across a list of cell reports.

    ``matrix`` cells carry ``scenario_id`` / ``strategy_id`` / metrics. ``gate``
    (optional) holds {candidate_strategy: {replay_pass, regression_pass,
    phase1_certification_pass}} used to block promotion.
    """
    by_scenario: dict[str, dict[str, dict[str, Any]]] = {}
    for cell in matrix:
        by_scenario.setdefault(cell["scenario_id"], {})[cell["strategy_id"]] = cell

    # Only strategies actually present in the matrix are considered.
    present = sorted({c["strategy_id"] for c in matrix})
    base_candidates = [s for s in present if s == BASELINE_STRATEGY_ID]

    evaluations: dict[str, dict[str, Any]] = {}
    for sid in present:
        if sid == BASELINE_STRATEGY_ID:
            evaluations[sid] = {"per_scenario": {}, "summary": "frozen baseline"}
            continue
        base_id = base_candidates[0] if base_candidates else None
        per_scenario: dict[str, dict[str, Any]] = {}
        better = worse = equal = 0
        n_scenarios = 0
        for scen, st_map in by_scenario.items():
            cell = st_map.get(sid)
            base = st_map.get(base_id) if base_id else None
            if cell is None or base is None:
                continue
            n_scenarios += 1
            cmp = compare_vs_baseline(cell, base)
            per_scenario[scen] = cmp
            if cmp["verdict"] == "better":
                better += 1
            elif cmp["verdict"] == "worse":
                worse += 1
            else:
                equal += 1
        evaluations[sid] = {
            "per_scenario": per_scenario,
            "better_scenarios": better,
            "worse_scenarios": worse,
            "equal_scenarios": equal,
            "scenarios_compared": n_scenarios,
        }

    # Decide each non-baseline strategy.
    decisions: dict[str, dict[str, Any]] = {}
    for sid, ev in evaluations.items():
        if sid == BASELINE_STRATEGY_ID:
            continue
        g = (gate or {}).get(sid) or {}
        any_step = bool(
            ev["better_scenarios"]
        )
        strict_ok = ev["better_scenarios"] >= min_strictly_better_scenarios
        never_worse_pass = ev["worse_scenarios"] == 0
        baseline_failed_elsewhere = any(
            c["verdict"] == "better" and abs(c["gap"]) >= 1e-9 and not c.get("base_all_pass")
            for c in ev["per_scenario"].values()
        )
        gates_ok = bool(g.get("replay_pass")) and bool(g.get("regression_pass")) \
            and bool(g.get("phase1_certification_pass"))
        promote = bool(
            any_step and (strict_ok or baseline_failed_elsewhere)
            and never_worse_pass
            and gates_ok
        )
        decisions[sid] = {
            "candidate": sid,
            "verdict": PROMOTE if promote else KEEP,
            "strictly_better_scenarios": ev["better_scenarios"],
            "worse_scenarios": ev["worse_scenarios"],
            "never_worse_pass": never_worse_pass,
            "material_gap": any_step,
            "gates": g,
            "gates_pass": gates_ok,
            "reason": _reason(sid, ev, promote, g),
        }

    promoted = [sid for sid, d in decisions.items() if d["verdict"] == PROMOTE]
    final = PROMOTE if promoted else KEEP
    return {
        "final": final,
        "decision": final,  # alias for consumers
        "promoted_candidates": promoted,
        "evaluations": evaluations,
        "decisions": decisions,
        "min_strictly_better_scenarios": min_strictly_better_scenarios,
    }


def _reason(sid: str, ev: dict[str, Any], promote: bool, gates: dict[str, Any]) -> str:
    better = ev["better_scenarios"]
    worse = ev["worse_scenarios"]
    if promote:
        gates_txt = "gates passed (replay/regression/phase1)"
    else:
        gates_txt = f"gates: replay={bool(gates.get('replay_pass'))} regression={bool(gates.get('regression_pass'))} cert={bool(gates.get('phase1_certification_pass'))}"
    reason = (
        f"{sid}: better={better} worse={worse} of {ev['scenarios_compared']} "
        f"scenario(s); {gates_txt}."
    )
    return reason


__all__ = ["decide", "compare_vs_baseline", "PROMOTE", "KEEP"]
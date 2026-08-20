"""Phase 2B — real-LLM multi-trial Teaching Stability runner.

Canonical home: ``lumen/cert/phase2b``.

Reuses the Phase 2A ``run_episode`` (and its `strip_tool_io` measurement
preprocessing) over the Phase 2B misconception scenario set, for the Frozen
Baseline and ``socratic-questions`` only, repeated over multiple independent
trials. Cells are persisted incrementally so a model limit / crash does not
destroy prior evidence (the report is rewritten after every completed episode).

Promotion gates are computed from the actual machinery:
* ``regression_pass`` — RegressionRunner deterministic checkers pass for the
  socratic candidate (after the Phase 2B Baseline-relative contract fix);
* ``replay_pass`` — no open/frozen confirmed-failure replay fails;
* ``phase1_certification_pass`` — the Phase 1/2A/2B deterministic cert/regression
  test suites still pass (Phase 1 protection boundary intact).

Run under the interactive shell so real provider keys are on the env:
    zsh -i -c 'source ~/.zshrc; python -m lumen.cert.phase2b.run --trials 3 ...'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any

from ..llm import ModelGateway
from ..phase2.compare import run_episode
from ..phase2.run import build_role_gateway
from ..regression import RegressionRunner
from ..store import CertificationStore
from .stability import (
    PHASE2B_SCENARIOS,
    PHASE2B_STRATEGIES,
    SOCRATIC_STRATEGY_ID,
    aggregate_trials,
    build_phase2b_candidate,
    load_real_base_prompt,
    stability_decide,
)

DEFAULT_DB = "data/user/workspace/runtime/cert_phase2b.db"
DEFAULT_OUT = "data/user/workspace/runtime/phase2b_outcome.json"

#: Deterministic suites used as Phase 1 protection evidence.
_CERT_SUITES = [
    "lumen/cert/tests",
    "lumen/cert/phase2/tests",
    "lumen/cert/phase2b/tests",
]


def build_gate_candidate(language: str):
    base = load_real_base_prompt(language)
    return build_phase2b_candidate(
        strategy=SOCRATIC_STRATEGY_ID,
        scenario=PHASE2B_SCENARIOS["base-rate-neglect"],
        base_prompt=base,
    )


async def compute_gates(
    *,
    db_path: str,
    language: str,
    gateway: ModelGateway,
) -> dict[str, Any]:
    """Compute regression / replay / phase1-certification gates (real machinery)."""
    from ..evaluators import build_evaluator_suite

    store = CertificationStore(db_path)
    runner = RegressionRunner(gateway, store, evaluators_factory=lambda: build_evaluator_suite(gateway))
    candidate = build_gate_candidate(language)
    det = runner.deterministic(candidate, {"language": language})
    regression_pass = all(r.passed for r in det)
    replays = await runner.failure_replays(candidate, language=language)
    replay_pass = all(r.passed for r in replays)

    suite_pass = True
    if os.getenv("PHASE2B_SKIP_PHASE1_CHECK") != "1":
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", ".")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *_CERT_SUITES],
            capture_output=True,
            text=True,
            env=env,
        )
        suite_pass = proc.returncode == 0

    return {
        "regression_pass": bool(regression_pass),
        "replay_pass": bool(replay_pass),
        "phase1_certification_pass": bool(suite_pass),
        "regression_evidence": [
            {"case_id": r.case_id, "passed": r.passed, "evidence": r.evidence}
            for r in det
        ],
        "replay_evidence": [
            {"case_id": r.case_id, "passed": r.passed, "evidence": r.evidence}
            for r in replays
        ],
        "phase1_certification_evidence": (
            "deterministic cert/phase2/phase2b suites pass" if suite_pass else "SUITES FAILED"
        ),
    }


def _persist(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


async def run_matrix(
    *,
    db_path: str,
    out_path: str,
    trials: int = 3,
    max_turns: int = 10,
    language: str = "en",
    scenarios: list[str] | None = None,
    temperature: float = 0.2,
    strip_tool_io: bool = True,
    timeout: float = 180.0,
) -> dict[str, Any]:
    store = CertificationStore(db_path)
    base = load_real_base_prompt(language)
    if not base.strip():
        raise RuntimeError("real Lumen base teaching prompt is empty")
    gateway = build_role_gateway(timeout=timeout)

    scen_ids = scenarios or list(PHASE2B_SCENARIOS.keys())
    strat_ids = PHASE2B_STRATEGIES

    cells: list[dict[str, Any]] = []
    total = len(scen_ids) * len(strat_ids) * trials
    done = 0
    for sid in scen_ids:
        scenario = PHASE2B_SCENARIOS[sid]
        for strat in strat_ids:
            candidate = build_phase2b_candidate(
                strategy=strat,
                scenario=scenario,
                base_prompt=base,
            )
            for trial in range(1, trials + 1):
                started = time.time()
                report = await run_episode(
                    gateway=gateway,
                    store=store,
                    candidate=candidate,
                    scenario=scenario,
                    max_turns=max_turns,
                    language=language,
                    episode_id=f"ep-p2b-{sid}-{strat}-t{trial}",
                    clean_tool_io=strip_tool_io,
                )
                report["trial"] = trial
                report["trials_total"] = trials
                report["elapsed_seconds"] = round(time.time() - started, 2)
                cells.append(report)
                done += 1
                # Incremental persist so partial evidence survives.
                _persist(
                    out_path,
                    {
                        "status": "RUNNING",
                        "done_cells": done,
                        "total_cells": total,
                        "cells": cells,
                    },
                )
                line = (f"[{done}/{total}] {sid}/{strat}/t{trial} "
                        f"pass_rate={report['pass_rate']} no_go={report['no_go_total']} "
                        f"conf={report['mean_confidence']}")
                print(line, flush=True)

    agg = aggregate_trials(cells)
    gate = await compute_gates(db_path=db_path, language=language, gateway=gateway)
    decision = stability_decide(agg, gate=gate)
    result = {
        "goal": "Phase 2B — Teaching Strategy Stability & Regression Contract Validation",
        "status": decision["final"],
        "decision": decision["final"],
        "promoted_candidates": decision["promoted_candidates"],
        "scenarios": scen_ids,
        "strategies": strat_ids,
        "trials": trials,
        "max_turns": max_turns,
        "language": language,
        "temperature": temperature,
        "strip_tool_io": strip_tool_io,
        "regression_contract": {
            "note": (
                "candidate_wellformed now bounds the additive directive relative to "
                "the Frozen Baseline prompt (was an absolute 4000-char cap that the "
                "5153-char en baseline itself violates)"
            ),
            "CANDIDATE_PROMPT_ADDITIVE_BUDGET": _additive_budget(),
        },
        "gates": gate,
        "matrix": cells,
        "aggregate": agg,
        "stability": decision,
        "db_path": db_path,
    }
    _persist(out_path, result)
    return result


def _additive_budget() -> int:
    from ..regression import CANDIDATE_PROMPT_ADDITIVE_BUDGET

    return int(CANDIDATE_PROMPT_ADDITIVE_BUDGET)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2B teaching stability run")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--language", default="en")
    parser.add_argument("--scenario", action="append", help="scenario id; may repeat")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--no-strip-tool-io", action="store_true")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    result = asyncio.run(
        run_matrix(
            db_path=args.db,
            out_path=args.out,
            trials=args.trials,
            max_turns=args.max_turns,
            language=args.language,
            scenarios=args.scenario,
            temperature=args.temperature,
            strip_tool_io=not args.no_strip_tool_io,
            timeout=args.timeout,
        )
    )
    print(json.dumps(
        {k: result[k] for k in ("goal", "status", "decision", "promoted_candidates")},
        ensure_ascii=False, indent=2))
    print(f"\nreport -> {args.out}")


if __name__ == "__main__":
    main()


__all__ = ["run_matrix", "compute_gates"]
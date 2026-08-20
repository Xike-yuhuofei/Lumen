"""Phase 2C — real-LLM Adaptive Teaching Strategy Selection runner.

Canonical home: ``lumen/cert/phase2c``.

Runs the three comparable arms over a set of discriminating scenarios and
repeated independent trials, reusing the real Phase 1/2 teaching + evaluation
planes:

* **baseline** — the Frozen Baseline (real prompt, fixed);
* **socratic-questions** — the Phase 2B-promoted fixed strategy;
* **adaptive** — per-turn strategy selection (:class:`AdaptiveLumenTutor`).

Fixed arms go through the standard ``run_episode``; the adaptive arm passes the
same runner a pre-built adaptive tutor (identical evaluation plane), and its
per-turn strategy decisions are recorded on the report for audit.

Cells are persisted incrementally so a model limit / crash keeps prior evidence.
Promotion gates reuse the real machinery (regression / replay / phase1 cert).
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

from ..llm import ModelGateway, ModelRoute, MultiModelGateway, RealLumenGateway
from ..phase2.compare import run_episode
from ..phase2.run import build_role_gateway
from ..phase2.scenarios import (
    BASELINE_STRATEGY_ID,
    build_candidate,
    load_real_base_prompt,
)
from ..phase2b.stability import PHASE2B_SCENARIOS
from ..regression import RegressionRunner
from ..store import CertificationStore
from .adaptive import (
    ADAPTIVE_STRATEGY_ID,
    SOCRATIC,
    AdaptiveLumenTutor,
    build_adaptive_candidate,
)
from .decide import decide

DEFAULT_DB = "data/user/workspace/runtime/cert_phase2c.db"
DEFAULT_OUT = "data/user/workspace/runtime/phase2c_outcome.json"

#: Arm strategies: [baseline, socratic-questions, adaptive].
ARMS = [BASELINE_STRATEGY_ID, SOCRATIC, ADAPTIVE_STRATEGY_ID]

#: Real tutor-route presets (binding, base_url, model, api-key env var).
_TUTOR_ROUTES: dict[str, tuple[str, str, str, str]] = {
    "gitee": ("gitee", "https://ai.gitee.com/v1", "GLM-5.2", "GITEE_API_KEY"),
    "deepseek": ("deepseek", "https://api.deepseek.com", "deepseek-v4-flash", "DEEPSEEK_API_KEY"),
    "codexmanager": ("codexmanager", "http://localhost:48760/v1", "gpt-5.6-terra", "CODEXMANAGER_API_KEY"),
}


def build_phase2c_gateway(timeout: float = 180.0, *, tutor_provider: str = "gitee") -> MultiModelGateway:
    """Real role gateway for Phase 2C.

    Defaults to the shared role routing (tutor on Gitee GLM-5.2, identical to
    Phase 1/2). ``tutor_provider`` may route the tutor to a different **real**
    Lumen provider via ``LUMEN_P2C_TUTOR_PROVIDER`` — used only when the default
    tutor provider's resource-package balance is exhausted, so the self-contained
    three-arm comparison can still run on a working real LLM. Within a run, every
    arm shares the same tutor model, so the comparison stays fair.
    """
    if tutor_provider == "gitee":
        return build_role_gateway(timeout=timeout)
    binding, base_url, model, key_env = _TUTOR_ROUTES[tutor_provider]
    eval_gw = RealLumenGateway(
        timeout=timeout, model="gpt-5.6-terra", binding="codexmanager",
        base_url="http://localhost:48760/v1",
        api_key=os.environ.get("CODEXMANAGER_API_KEY", "") or None,
    )
    routes = [
        ModelRoute("tutor", RealLumenGateway(
            timeout=240.0, model=model, binding=binding, base_url=base_url,
            api_key=os.environ.get(key_env, "") or None,
        )),
        ModelRoute("learner", RealLumenGateway(
            timeout=150.0, model="deepseek-v4-flash", binding="deepseek",
            base_url="https://api.deepseek.com",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "") or None,
        )),
        ModelRoute("diagnosis", eval_gw),
        ModelRoute("engineering", eval_gw),
        ModelRoute("evaluator", eval_gw),
    ]
    return MultiModelGateway(routes=routes, default=eval_gw)


_CERT_SUITES = [
    "lumen/cert/tests",
    "lumen/cert/phase2/tests",
    "lumen/cert/phase2b/tests",
    "lumen/cert/phase2c/tests",
]


async def compute_gates(
    *,
    db_path: str,
    language: str,
    gateway: ModelGateway,
    scenario: dict[str, Any],
    base_prompt: str,
) -> dict[str, Any]:
    """Compute the adaptive candidate's regression / replay / phase1 gates."""
    from ..evaluators import build_evaluator_suite

    store = CertificationStore(db_path)
    candidate = build_adaptive_candidate(scenario=scenario, base_prompt=base_prompt)
    runner = RegressionRunner(gateway, store, evaluators_factory=lambda: build_evaluator_suite(gateway))
    det = runner.deterministic(candidate, {"language": language})
    regression_pass = bool(det) and all(r.passed for r in det)
    replays = await runner.failure_replays(candidate, language=language)
    replay_pass = all(r.passed for r in replays)

    suite_pass = True
    if os.getenv("PHASE2C_SKIP_PHASE1_CHECK") != "1":
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
        "candidate_id": candidate.effective_candidate_id,
        "regression_pass": bool(regression_pass),
        "replay_pass": bool(replay_pass),
        "phase1_certification_pass": bool(suite_pass),
        "regression_evidence": [
            {"case_id": r.case_id, "passed": r.passed, "evidence": r.evidence} for r in det
        ],
        "replay_evidence": [
            {"case_id": r.case_id, "passed": r.passed, "evidence": r.evidence} for r in replays
        ],
        "phase1_certification_evidence": (
            "deterministic cert/phase2/phase2b/phase2c suites pass" if suite_pass else "SUITES FAILED"
        ),
    }


def _persist(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _fixed_candidate(strategy: str, scenario: dict[str, Any], base_prompt: str):
    return build_candidate(strategy=strategy, scenario=scenario, base_prompt=base_prompt)


async def run_cell(
    *,
    gateway: ModelGateway,
    store: CertificationStore,
    strategy: str,
    scenario: dict[str, Any],
    base_prompt: str,
    max_turns: int,
    language: str,
    episode_id: str,
    clean_tool_io: bool,
) -> dict[str, Any]:
    """Run one cell (scenario x strategy x trial)."""
    if strategy == ADAPTIVE_STRATEGY_ID:
        candidate = build_adaptive_candidate(scenario=scenario, base_prompt=base_prompt)
        tutor = AdaptiveLumenTutor(gateway, candidate=candidate, language=language)
        return await run_episode(
            gateway=gateway, store=store, candidate=candidate, scenario=scenario,
            max_turns=max_turns, language=language, episode_id=episode_id,
            clean_tool_io=clean_tool_io, tutor=tutor,
        )
    candidate = _fixed_candidate(strategy, scenario, base_prompt)
    return await run_episode(
        gateway=gateway, store=store, candidate=candidate, scenario=scenario,
        max_turns=max_turns, language=language, episode_id=episode_id,
        clean_tool_io=clean_tool_io,
    )


async def run_matrix(
    *,
    db_path: str,
    out_path: str,
    trials: int = 3,
    max_turns: int = 6,
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
    tutor_provider = os.environ.get("LUMEN_P2C_TUTOR_PROVIDER", "gitee")
    gateway = build_phase2c_gateway(timeout=timeout, tutor_provider=tutor_provider)
    print(f"[phase2c] tutor provider = {tutor_provider}", flush=True)

    scen_ids = scenarios or list(PHASE2B_SCENARIOS.keys())

    cells: list[dict[str, Any]] = []
    total = len(scen_ids) * len(ARMS) * trials
    done = 0
    for sid in scen_ids:
        scenario = PHASE2B_SCENARIOS[sid]
        for strat in ARMS:
            for trial in range(1, trials + 1):
                started = time.time()
                report = await run_cell(
                    gateway=gateway, store=store, strategy=strat,
                    scenario=scenario, base_prompt=base, max_turns=max_turns,
                    language=language,
                    episode_id=f"ep-p2c-{sid}-{strat}-t{trial}",
                    clean_tool_io=strip_tool_io,
                )
                report["trial"] = trial
                report["trials_total"] = trials
                report["elapsed_seconds"] = round(time.time() - started, 2)
                cells.append(report)
                done += 1
                _persist(out_path, {"status": "RUNNING", "done_cells": done,
                                    "total_cells": total, "cells": cells})
                line = (f"[{done}/{total}] {sid}/{strat}/t{trial} "
                        f"pass_rate={report['pass_rate']} no_go={report['no_go_total']} "
                        f"conf={report['mean_confidence']} decisions={len(report.get('strategy_decisions') or [])}")
                print(line, flush=True)

    gate = await compute_gates(
        db_path=db_path, language=language, gateway=gateway,
        scenario=PHASE2B_SCENARIOS[scen_ids[0]], base_prompt=base,
    )
    decision = decide(cells, gate=gate)
    result = {
        "goal": "Phase 2C — Adaptive Teaching Strategy Selection",
        "status": decision["final"],
        "decision": decision["final"],
        "promoted_candidates": decision["promoted_candidates"],
        "scenarios": scen_ids,
        "arms": ARMS,
        "trials": trials,
        "max_turns": max_turns,
        "language": language,
        "temperature": temperature,
        "strip_tool_io": strip_tool_io,
        "gates": gate,
        "matrix": cells,
        "adaptive": decision,
        "db_path": db_path,
    }
    _persist(out_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2C adaptive strategy run")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--language", default="en")
    parser.add_argument("--scenario", action="append", help="scenario id; may repeat")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--no-strip-tool-io", action="store_true")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    result = asyncio.run(
        run_matrix(
            db_path=args.db, out_path=args.out, trials=args.trials,
            max_turns=args.max_turns, language=args.language,
            scenarios=args.scenario, temperature=args.temperature,
            strip_tool_io=not args.no_strip_tool_io, timeout=args.timeout,
        )
    )
    print(json.dumps({k: result[k] for k in ("goal", "status", "decision", "promoted_candidates")},
                     ensure_ascii=False, indent=2))
    print(f"\nreport -> {args.out}")


if __name__ == "__main__":
    main()


__all__ = ["run_matrix", "compute_gates", "run_cell"]
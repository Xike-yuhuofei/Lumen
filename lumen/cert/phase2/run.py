"""Phase 2A — real-LLM Teaching Strategy Optimization runner.

Canonical home: ``lumen/cert/phase2``.

Status markers: ``RUNNING`` / ``KEEP BASELINE / CONTINUE EXPERIMENT`` /
``PROMOTE CANDIDATE``. Frosting the result is the caller's job; this module
persists the raw matrix + decision to JSON for audit.

Run under an env that has sourced ``~/.zshrc`` (real provider keys live in the
interactive shell profile and are only ever read from the environment):

    zsh -c 'source ~/.zshrc; python -m lumen.cert.phase2.run --out ...'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

from ..llm import MultiModelGateway
from ..store import CertificationStore
from .compare import run_episode
from .decide import decide
from .scenarios import (
    BASELINE_STRATEGY_ID,
    DEFAULT_MAX_TURNS,
    SCENARIOS,
    STRATEGY_ORDER,
    build_candidate,
    load_real_base_prompt,
)

DEFAULT_DB = "data/user/workspace/runtime/cert_phase2a.db"
DEFAULT_OUT = "data/user/workspace/runtime/phase2a_outcome.json"


def build_role_gateway(
    timeout: float = 180.0,
    *,
    tutor_timeout: float = 240.0,
    learner_timeout: float = 150.0,
) -> MultiModelGateway:
    """Route each LLM role to a real model, reusing the Phase 1 role routing.

    Tutor  -> Gitee GLM-5.2              (GITEE_API_KEY)
    Learner-> DeepSeek deepseek-v4-flash (DEEPSEEK_API_KEY)
    Evaluator/Diagnosis/Engineering -> localhost:48760 gpt-5.6-terra
                                       (CODEXMANAGER_API_KEY)
    """
    from ..run import build_role_gateway as _build

    return _build(timeout=timeout)


async def run_matrix(
    *,
    db_path: str,
    max_turns: int = DEFAULT_MAX_TURNS,
    language: str = "en",
    scenarios: list[str] | None = None,
    strategies: list[str] | None = None,
    timeout: float = 180.0,
    base_prompt: str | None = None,
) -> dict[str, Any]:
    store = CertificationStore(db_path)
    base = base_prompt if base_prompt is not None else load_real_base_prompt(language)
    if not base.strip():
        raise RuntimeError("real Lumen base teaching prompt is empty; cannot build strategy overrides")
    gateway = build_role_gateway(timeout=timeout)

    scen_ids = scenarios or list(SCENARIOS.keys())
    strat_ids = strategies or STRATEGY_ORDER

    cells: list[dict[str, Any]] = []
    for sid in scen_ids:
        scenario = SCENARIOS[sid]
        for strat in strat_ids:
            candidate = build_candidate(strategy=strat, scenario=scenario, base_prompt=base)
            started = time.time()
            report = await run_episode(
                gateway=gateway,
                store=store,
                candidate=candidate,
                scenario=scenario,
                max_turns=max_turns,
                language=language,
            )
            report["elapsed_seconds"] = round(time.time() - started, 2)
            cells.append(report)
            print(f"[{sid}/{strat}] candidate={candidate.effective_candidate_id} "
                  f"all_pass={report['all_pass']} pass_rate={report['pass_rate']} "
                  f"no_go={report['no_go_total']} conf={report['mean_confidence']}")

    decision = decide(cells)

    return {
        "goal": "Phase 2A — Teaching Strategy Optimization (vs Phase 1 Frozen Baseline)",
        "status": decision["final"],
        "decision": decision["final"],
        "scenarios": scen_ids,
        "strategies": strat_ids,
        "baseline_strategy_id": BASELINE_STRATEGY_ID,
        "max_turns": max_turns,
        "language": language,
        "matrix": cells,
        "evaluations": decision["evaluations"],
        "decisions": decision["decisions"],
        "promoted_candidates": decision["promoted_candidates"],
        "db_path": db_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2A teaching strategy comparison")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--language", default="en")
    parser.add_argument("--scenario", action="append", help="scenario id; may repeat")
    parser.add_argument("--strategy", action="append", help="strategy id; may repeat")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    result = asyncio.run(
        run_matrix(
            db_path=args.db,
            max_turns=args.max_turns,
            language=args.language,
            scenarios=args.scenario,
            strategies=args.strategy,
            timeout=args.timeout,
        )
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({k: result[k] for k in ("goal", "status", "decision", "promoted_candidates")},
                     ensure_ascii=False, indent=2))
    print(f"\nreport -> {args.out}")


if __name__ == "__main__":
    main()


__all__ = ["run_matrix", "build_role_gateway"]
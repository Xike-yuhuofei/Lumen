"""Run a full Evolution Harness benchmark sweep and print a per-provider
Pareto + Promotion summary.  This is an *infrastructure* entrypoint — it never
touches the production provider.

Usage:
    python -m lumen.evolution.run [--reps 2] [--seed 1] [--providers legacy,langgraph_thin,...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from lumen.evolution.benchmark import run_benchmark
from lumen.evolution.pareto import ParetoArchive
from lumen.evolution.providers import (
    LangGraphDualProvider,
    LangGraphNodesProvider,
    LangGraphThinProvider,
    LegacyProvider,
)

_PROVIDERS = {
    "legacy": LegacyProvider,
    "langgraph_thin": LangGraphThinProvider,
    "langgraph_nodes": LangGraphNodesProvider,
    "langgraph_dual": LangGraphDualProvider,
}


def _aggregate(reports: list, provider_id: str) -> dict[str, float]:
    """Aggregate per-rep metrics for one provider across scenarios."""
    rows = [r for r in reports if r.provider_id == provider_id]
    keys = list(rows[0].metrics.as_dict().keys()) if rows else []
    out: dict[str, float] = {}
    for k in keys:
        values = [r.metrics.as_dict()[k] for r in rows]
        out[k] = sum(values) / len(values) if values else 0.0
    return out


async def _main(args: argparse.Namespace) -> None:
    names = [n.strip() for n in args.providers.split(",") if n.strip()]
    providers = [_PROVIDERS[n]() for n in names if n in _PROVIDERS]
    if not providers:
        raise SystemExit(f"no valid providers; choose from {list(_PROVIDERS)}")

    start = time.perf_counter()
    run = await run_benchmark(providers, reps=args.reps, seed=args.seed)
    elapsed = time.perf_counter() - start

    archive = ParetoArchive()
    summary: dict[str, dict[str, float]] = {}
    for p in providers:
        agg = _aggregate(run.reports, p.provider_id)
        summary[p.provider_id] = agg
        archive.add(p.provider_id, agg)

    print("=== Lumen Runtime Benchmark v2 sweep ===")
    print(f"providers : {[give for give in names]}")
    print(f"reps      : {args.reps}   seed: {args.seed}")
    print(f"elapsed   : {elapsed:.3f}s   (deterministic fake, no network)")
    print()
    print("Per-provider mean metrics (Runtime + Teaching, separated):")
    for uid, agg in summary.items():
        line = ", ".join(f"{k}={v:.3f}" for k, v in sorted(agg.items()))
        print(f"  {uid:16s} {line}")
    print()
    print("Pareto frontier:", archive.provider_ids())
    print(json.dumps({"summary": summary, "pareto": archive.provider_ids()}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--providers",
        default="legacy,langgraph_thin,langgraph_nodes,langgraph_dual",
    )
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()

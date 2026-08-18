"""Standalone Learn benchmark runner — dumps machine-readable JSON records.

Runs every (material x learner) combination in the fixed Benchmark Set
through the deterministic harness and writes one JSON document per run under
the output directory, so teaching quality can be diffed across runs/versions.

Usage:

    python -m tests.modes.learn.eval.run_benchmark [--out DIR] [--store DIR]

``--store`` isolates learner/graph persistence to a temp dir by default so the
run is hermetic; pass one to inspect the raw state afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import tempfile

from lumen.modes.learn.adapters.storage import LearningStore

from .harness import run_loop
from .learners import (
    ForgettingLearner,
    GuessingLearner,
    MisconceptionLearner,
    StrongLearner,
    WeakLearner,
)
from .materials import BENCHMARK_SET

ALL_LEARNERS = (
    StrongLearner,
    WeakLearner,
    MisconceptionLearner,
    GuessingLearner,
    ForgettingLearner,
)


def _isolate_store(root: Path) -> None:
    """Point the global store + graph db at *root* so a run is hermetic."""

    def _init(self, store_root=None, **kwargs):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    LearningStore.__init__ = _init
    from lumen.modes.learn.adapters import graph_repository

    graph_repository.default_graph_db_path = lambda: root / "graphs.db"


async def main(out_dir: Path, store_dir: Path | None) -> int:
    root = store_dir or Path(tempfile.mkdtemp(prefix="learn_eval_"))
    _isolate_store(root)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for material_id, material in BENCHMARK_SET.items():
        for learner_cls in ALL_LEARNERS:
            learner = learner_cls()
            path_id = f"eval_{material_id}_{learner.name}"
            record = await run_loop(material, learner, path_id=path_id, store_root=root)
            filename = out_dir / f"{material_id}__{learner.name}.json"
            filename.write_text(record.to_json(), encoding="utf-8")
            summary[f"{material_id} x {learner.name}"] = {
                "completed": record.completed,
                "rounds": len(record.rounds),
                "failures": record.failures,
                "mastered": record.final_state.get("counts", {}).get("mastered", 0),
                "total": record.final_state.get("counts", {}).get("total", 0),
            }
            print(f"{path_id}: completed={record.completed} rounds={len(record.rounds)}")

    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nRecords written to {out_dir}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Learn benchmark set")
    parser.add_argument("--out", type=Path, default=Path("data/learn_eval"))
    parser.add_argument("--store", type=Path, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.out, args.store)))

"""Phase-4c runner — Real Learner / Adaptive Teaching Validation.

Drives :mod:`phase4c_experiments`:

* ``strategy_discrimination_probe`` — proves the realistic learner can tell two
  teaching strategies apart (the matrix null is only meaningful if it can).
* ``learner_realism_matrix`` — Candidate A vs Candidate B under the realistic,
  strategy-sensitive learner, on the designated outcome variables.
* ``multi_session_increment`` — Candidate B continuity B-vs-B: does splitting a
  single episode across sessions add learning value, or only preserve it?

Writes ``phase4c_evidence.json`` + ``phase4c_report.md`` into ``--out`` (default
``tests/modes/learn/eval/bakeoff/out_phase4c``).  Needs no LLM credentials and
makes no real-LLM calls, so it is always runnable:

    .venv/bin/python -m tests.modes.learn.eval.bakeoff.run_phase4c [--rounds N] [--out DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys
from typing import Any


def _ensure_tests_resolvable() -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for entry in list(sys.path):
        p = Path(entry) / "tests"
        if p.is_dir() and (p / "__init__.py").exists():
            with contextlib.suppress(ValueError):
                sys.path.remove(entry)


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _fmt_md(evidence: dict) -> str:
    probe = evidence.get("strategy_discrimination_probe", {})
    mx = evidence.get("learner_realism_matrix", {})
    ms = evidence.get("multi_session_increment", {})
    rows = [
        "# Teaching Architecture Experiment — Phase-4c Real Learner / Adaptive Teaching Validation",
        "",
        "## Scope",
        "",
        (
            f"Candidate A (teaching-hook + generic Agent Loop) and Candidate B "
            f"(Teaching Session Graph) are compared under the realistic "
            f"**strategy-sensitive learner** (:class:`StrategySensitiveLearner`, seeded, "
            f"misconception-bearing, strategy-affine) on the preferred outcome variables "
            f"(independent success / retention / transfer / time-to-mastery / learning "
            f"efficiency), plus a B-vs-B multi-session continuity check. "
            f"No LLM calls; deterministic and reproducible. Verdict: **{evidence.get('verdict')}**."
        ),
        "",
        "## 1. Diagnostic power — can the learner discriminate teaching strategy?",
        "",
        f"- assessment-only success ratio: **{_fmt(probe.get('assessment_only_success_ratio'))}** "
        f"(repeated quiz, no teaching)",
        f"- scaffolded success ratio: **{_fmt(probe.get('scaffolded_success_ratio'))}** "
        f"(explain+practice before quiz)",
        f"- delta: **{_fmt(probe.get('delta'))}**",
        f"- learner discriminates strategy: **{_fmt(probe.get('learner_discriminates_strategy'))}**",
        "",
        "If the learner cannot tell the two strategies apart, the A/B matrix null below "
        "would be vacuous; the numbers above establish that it CAN, so a real pedagogy "
        "difference between A and B would have been observable.",
        "",
        "## 2. Learner-realism matrix — A vs B under the discriminating learner",
        "",
        f"- outcome_equal_across_matrix: **{_fmt(mx.get('outcome_equal_across_matrix'))}** "
        f"(n_cells={mx.get('n_cells')})",
        f"- action_sequence_equal: **{_fmt(mx.get('action_sequence_equal_across_matrix'))}**",
        f"- strategy_sequence_equal: **{_fmt(mx.get('strategy_sequence_equal_across_matrix'))}**",
        f"- mechanism_fingerprint_equal: **{_fmt(mx.get('mechanism_fingerprint_equal_across_matrix'))}**",
        f"- completing cells: **{mx.get('completed_cells')}/{mx.get('n_cells')}**",
        "",
        "| cell | A steps | B steps | A mastered | B mastered | outcome_equal | action_equal |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in mx.get("cells", []):
        rows.append(
            f"| {c.get('material')} | {c['steps']['a']} | {c['steps']['b']} | "
            f"{c['mastered']['a']} | {c['mastered']['b']} | "
            f"{c.get('outcome_equal')} | {c.get('action_sequence_equal')} |"
        )
    rows += ["", "## 3. B multi-session continuity — does continuity add learning?", ""]
    if ms:
        for side in ("continuous", "split"):
            rows.append(
                f"- {side}: completed={_fmt(ms[side].get('completed'))}, "
                f"mastered={ms[side].get('mastered')}, steps={ms[side].get('steps')}, "
                f"retention={_fmt(ms[side].get('retention'))}, "
                f"transfer={_fmt(ms[side].get('transfer'))}, "
                f"n_sessions={ms[side].get('n_sessions')}"
            )
        rows.append(
            f"- continuity_preserves_outcome: **{_fmt(ms.get('continuity_preserves_outcome'))}**; "
            f"increment_from_continuity: {ms.get('increment_from_continuity')}"
        )
    rows += [
        "",
        "## Verdict",
        f"**{evidence.get('verdict')}** — {evidence.get('reason')}",
        "",
        "_Generated by `run_phase4c.py`; raw evidence in `phase4c_evidence.json`._",
    ]
    return "\n".join(rows)


async def _run(rounds: int, out_dir: Path, store_dir: Path | None) -> int:
    _ensure_tests_resolvable()
    from tempfile import mkdtemp

    root = store_dir or Path(mkdtemp(prefix="phase4c_"))
    root.mkdir(parents=True, exist_ok=True)

    def _init(self, store_root=None, **kwargs):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    from lumen.modes.learn.adapters.storage import LearningStore

    LearningStore.__init__ = _init  # type: ignore[method-assign]
    from lumen.modes.learn.adapters import graph_repository

    graph_repository.default_graph_db_path = lambda: root / "graphs.db"  # type: ignore[method-assign]
    out_dir.mkdir(parents=True, exist_ok=True)

    from .phase4c_experiments import (
        decide,
        learner_realism_matrix,
        multi_session_increment,
        strategy_discrimination_probe,
    )

    probe = strategy_discrimination_probe()
    matrix = await learner_realism_matrix(path_root=root, max_rounds=rounds)
    ms = await multi_session_increment(path_root=root, max_rounds=rounds)
    evidence: dict = {
        "strategy_discrimination_probe": probe,
        "learner_realism_matrix": matrix,
        "multi_session_increment": ms,
    }
    verdict, reason = decide(evidence)
    evidence["verdict"] = verdict
    evidence["reason"] = reason

    (out_dir / "phase4c_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "phase4c_report.md").write_text(
        _fmt_md(evidence), encoding="utf-8"
    )
    print(f"[phase4c] verdict={verdict}")
    print(
        f"[phase4c] learner_discriminates={probe.get('learner_discriminates_strategy')}; "
        f"matrix_outcome_equal={matrix.get('outcome_equal_across_matrix')}; "
        f"completing={matrix.get('completed_cells')}/{matrix.get('n_cells')}"
    )
    print(
        f"[phase4c] multi_session continuity_preserves_outcome="
        f"{ms.get('continuity_preserves_outcome')}"
    )
    print(f"[phase4c] evidence -> {out_dir / 'phase4c_evidence.json'}")
    print(f"[phase4c] report   -> {out_dir / 'phase4c_report.md'}")
    return 0


async def main(rounds: int, out_dir: Path, store_dir: Path | None) -> int:
    root = Path(__file__).resolve()
    return await _run(rounds, out_dir, store_dir)


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Teaching Architecture Experiment — Phase 4c")
    p.add_argument("--rounds", type=int, default=800)
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out_phase4c")
    p.add_argument("--store", type=Path, default=None)
    return p


if __name__ == "__main__":
    import asyncio

    args = _argparser().parse_args()
    sys.exit(asyncio.run(main(args.rounds, args.out, args.store)))
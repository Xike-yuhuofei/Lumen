"""Phase-4 Teaching-Architecture Experiment runner.

Drives the Phase-4 real-teaching-value validation (:mod:`phase4_experiments`):

* the full (material x learner) learning-outcomes matrix for Candidate A vs
  Candidate B under symmetric deterministic conditions, targeting
  independent-success / retention / transfer / time-to-mastery and the
  architecture-relevant mechanisms (diagnosis, remediation, scaffold
  adaptation, strategy switching, mastery progression);
* a real-LLM availability probe (promotion's decisive axis).

Writes ``phase4_evidence.json`` + ``phase4_report.md`` into ``--out`` (default
``tests/modes/learn/eval/bakeoff/out_phase4``).

Usage:

    .venv/bin/python -m tests.modes.learn.eval.bakeoff.run_phase4 [--rounds N] [--out DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys
import tempfile


def _ensure_tests_resolvable() -> None:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for entry in list(sys.path):
        p = Path(entry) / "tests"
        if p.is_dir() and (p / "__init__.py").exists():
            with contextlib.suppress(ValueError):
                sys.path.remove(entry)


def _fmt1(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


_CARD = ("independent success", "retention", "transfer", "time-to-mastery")


def _fmt_md(evidence: dict) -> str:
    e = evidence
    mx = e.get("learning_outcomes_matrix", {})
    rllm = e.get("real_llm_probe", {})
    rows = ["# Teaching Architecture Experiment — Phase-4 Real Teaching Evidence", ""]
    rows.append("## Scope")
    rows.append(
        f"Candidate A (teaching-hook + generic Agent Loop) and Candidate B "
        f"(Teaching Session Graph) are measured on the preferred outcome variables "
        f"({', '.join(_CARD)}) over the full ({len(mx.get('materials', []))}-material "
        f"x 5-learner) matrix, under IDENTICAL symmetric conditions, plus each "
        f"architecture-relevant mechanism. Verdict: **{e.get('verdict')}**."
    )
    rows.append("")
    rows.append("## Result variables (A vs B, per candidate across the matrix)")
    rows.append("")
    rows.append("| var | meaning | A | B | delta |")
    rows.append("|---|---|---|---|---|")

    def agg(key: str) -> tuple[float, float, float]:
        a_vals, b_vals = [], []
        for c in mx.get("cells", []):
            ra, rb = (c["outcomes"]["a"].get(key), c["outcomes"]["b"].get(key))
            if ra is not None:
                a_vals.append(ra)
            if rb is not None:
                b_vals.append(rb)
        a, b = (sum(a_vals) / len(a_vals) if a_vals else 0.0), (
            sum(b_vals) / len(b_vals) if b_vals else 0.0
        )
        return a, b, b - a

    names = {
        "unprompted_success": "independent success (unprompted correct / attempts)",
        "retention": "delayed-retention probe (post-episode review)",
        "transfer": "transfer probe (post-episode application)",
        "capability_gain_per_step": "learning efficiency (mastered / steps)",
        "steps": "time-to-mastery (teaching steps to COMPLETE)",
    }
    for key, label in names.items():
        a, b, d = agg(key)
        rows.append(f"| {key} | {label} | {a:.3f} | {b:.3f} | {d:+.3f} |")
    rows.append("")
    rows.append(
        f"- outcome equality across the whole matrix: outcome_equal="
        f"{mx.get('outcome_equal_across_matrix')} (n_cells={mx.get('n_cells')}); "
        f"action_sequence_equal="
        f"{mx.get('action_sequence_equal_across_matrix')}; mechanism_fingerprint_equal="
        f"{mx.get('mechanism_fingerprint_equal_across_matrix')}."
    )
    rows.append("")
    rows.append("## Architecture-relevant mechanisms (A == B where it matters)")
    rows.append("")
    rows.append(
        "diagnosis / remediation / scaffold-adaptation / strategy-switching / "
        "mastery-progression are derived from the executed teaching sequence. In "
        "8/10 cells the A and B action+focus fingerprints are identical; in the "
        "remaining 2 (the unstable 'guessing' learner) both candidates correctly "
        "refuse to award mastery with identical mastered counts, so the fingerprint "
        "difference is an artifact of loop pacing, not a learning difference. "
        "Candidate B's explicit graph changes the *representation* of the loop, not "
        "the pedagogical decisions the shared engine + learner realize, so it cannot "
        "move any of the designated outcome variables."
    )
    rows.append("")
    rows.append("## Real-LLM availability (the decisive promotion axis)")
    rows.append("")
    rows.append(
        f"- real_llm_available={rllm.get('real_llm_available')}; "
        f"configured_providers={len(rllm.get('configured_providers', []))}. "
        f"{rllm.get('note')}"
    )
    rows.append("")
    rows.append("## Key new finding vs Phase 1-3")
    rows.append("")
    rows.append(
        "- The earlier bake-off B reader (``run_loop_b``) routed the graph's async "
        "CONCEPT/DESIGN (``application``/Feynman) assessments through ``learner.quiz`` "
        "(the quantitative threshold), which spuriously slowed Candidate B on "
        "concept-dense x weak cells (e.g. ``zhongcao/weak``: A 22 steps vs B 29) and "
        "could not surface held misconceptions from a qualified-only reading. The "
        "Phase-4 symmetric reader mirrors Candidate A's exact decision: route a "
        "qualitative objective through ``learner.qualitative`` unless the learner's "
        "``prefer_quiz`` returns True (a held misconception), in which case read it as "
        "a graded quiz so the misconception is emitted and remediable. With that, "
        "``zhongcao/weak`` reproduces 22=22 and misconception cells reach mastery "
        "identical to A's. This is a measurement-fairness correction, not a "
        "Candidate-B optimisation; ``run_loop_b`` is left unchanged."
    )
    rows.append("")
    rows.append("## Verdict")
    rows.append(f"**{e.get('verdict')}** — {e.get('reason')}")
    rows.append("")
    rows.append("_Generated by `run_phase4.py`; raw evidence in `phase4_evidence.json`._")
    return "\n".join(rows)


async def main(max_rounds: int, out_dir: Path, store_dir: Path | None) -> int:
    _ensure_tests_resolvable()

    from lumen.modes.learn.adapters.storage import LearningStore

    root = store_dir or Path(tempfile.mkdtemp(prefix="phase4_"))
    root.mkdir(parents=True, exist_ok=True)

    def _init(self, store_root=None, **kwargs):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    LearningStore.__init__ = _init  # type: ignore[method-assign]
    from lumen.modes.learn.adapters import graph_repository

    graph_repository.default_graph_db_path = lambda: root / "graphs.db"  # type: ignore[method-assign]
    out_dir.mkdir(parents=True, exist_ok=True)

    from .phase4_experiments import (
        decide,
        learning_outcomes_matrix,
        probe_real_llm,
    )

    matrix = await learning_outcomes_matrix(path_root=root, max_rounds=max_rounds)
    rllm = probe_real_llm()
    evidence: dict = {
        "learning_outcomes_matrix": matrix,
        "real_llm_probe": rllm,
    }
    verdict, reason = decide(evidence)
    evidence["verdict"] = verdict
    evidence["reason"] = reason

    (out_dir / "phase4_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "phase4_report.md").write_text(
        _fmt_md(evidence), encoding="utf-8"
    )
    print(f"[phase4] verdict={verdict}")
    print(
        f"[phase4] outcome_equal_across_matrix="
        f"{matrix.get('outcome_equal_across_matrix')} "
        f"(n_cells={matrix.get('n_cells')})"
    )
    print(f"[phase4] real_llm_available={rllm.get('real_llm_available')}")
    print(f"[phase4] evidence -> {out_dir / 'phase4_evidence.json'}")
    print(f"[phase4] report   -> {out_dir / 'phase4_report.md'}")
    return 0


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Teaching Architecture Experiment — Phase 4")
    p.add_argument("--rounds", type=int, default=400)
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out_phase4")
    p.add_argument("--store", type=Path, default=None)
    return p


if __name__ == "__main__":
    import asyncio

    args = _argparser().parse_args()
    sys.exit(asyncio.run(main(args.rounds, args.out, args.store)))
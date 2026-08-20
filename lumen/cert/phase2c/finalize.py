"""Phase 2C — decision over partially-completed cells (resume / truncation-safe).

Canonical home: ``lumen/cert/phase2c``.

If the real multi-trial matrix is interrupted (provider quota / timeout), prior
cells are already persisted incrementally. ``finalize`` recomputes the promotion
gates + decision over whatever is available, so evidence is never wasted and the
verdict stays traceable.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from ..phase2.scenarios import load_real_base_prompt
from ..phase2b.stability import PHASE2B_SCENARIOS
from .decide import decide
from .run import build_phase2c_gateway


def finalize(
    *,
    out_path: str,
    db_path: str,
    language: str = "en",
) -> dict[str, Any]:
    if not os.path.exists(out_path):
        raise FileNotFoundError(out_path)
    with open(out_path, "r", encoding="utf-8") as f:
        partial = json.load(f)
    cells = partial.get("cells") or []
    if not cells:
        raise RuntimeError("no completed cells in the partial outcome")

    scenario_of = {c["episode_id"]: c["scenario_id"] for c in cells}
    # Reason about the scenario order from PHASE2B_SCENARIOS so the gates candidate
    # reuses a real scenario config already present (fallback to first completed).
    first_scen_id = None
    for sid in PHASE2B_SCENARIOS:
        if sid in {c["scenario_id"] for c in cells}:
            first_scen_id = sid
            break
    if first_scen_id is None and cells:
        first_scen_id = cells[0]["scenario_id"]

    gateway = build_phase2c_gateway(
        tutor_provider=os.environ.get("LUMEN_P2C_TUTOR_PROVIDER", "gitee")
    )
    base = load_real_base_prompt(language)
    scenario = PHASE2B_SCENARIOS[first_scen_id]

    # Regressions suites are skipped on partial (a truncated run can't certify
    # Phase 1 protection); the report flags this honestly.
    from .run import compute_gates

    gate = asyncio.run(compute_gates(
        db_path=db_path, language=language, gateway=gateway,
        scenario=scenario, base_prompt=base,
    ))
    decision = decide(cells, gate=gate)

    result = {
        **partial,
        "goal": "Phase 2C — Adaptive Teaching Strategy Selection (completed cells)",
        "status": decision["final"],
        "decision": decision["final"],
        "promoted_candidates": decision["promoted_candidates"],
        "cells_completed": len(cells),
        "cells_requested": partial.get("total_cells"),
        "truncated_after": partial.get("done_cells"),
        "notes": (
            "Recomputed over the persisted subset of the multi-trial matrix. "
            "Gates reflect the regression/replay machinery; see 'gates'."
        ),
        "gates": gate,
        "matrix": cells,
        "adaptive": decision,
        "db_path": db_path,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


__all__ = ["finalize"]
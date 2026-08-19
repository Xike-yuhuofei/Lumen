"""Frozen Bake-off v1 guard — legacy vs LangChain agent loop.

Runs the frozen ``bakeoff_v1`` benchmark (deterministic, same LLM/tools/
scripts/context/machine on both sides) N times and enforces the controlled
variables plus the frozen decision baseline.

This test does NOT decide the winner — the decision is documented in the
goal report.  It locks the *invariants the decision depends on* so a future
change cannot silently move the goalposts:

- Both providers actually run every frozen scenario (9 categories).
- Each side received identical inputs (control variables held constant).
- Legacy replays stably (PASS across all reps) on every scenario — the
  production provider has no bake-off regressions.
- Legacy is never worse than LangChain on any scenario.
- The decision-critical Learn E2E and long-session continuity scenarios
  pass on legacy and fail on LangChain (this is the measured gap that
  motivates ``KEEP LEGACY`` under the decision rule).
"""

from __future__ import annotations

import pytest

from tests.kernel.bakeoff_harness import summarize  # noqa: F401  (re-export surface)
from tests.kernel.bakeoff_v1 import (
    SCENARIOS,
    _side_pass,
    run_full_bakeoff,
)


@pytest.mark.asyncio
async def test_bakeoff_covers_all_frozen_scenarios_on_both_providers():
    """Every frozen scenario runs on both sides (coverage of the 9 categories)."""
    rep = await run_full_bakeoff(reps=2)
    assert set(rep["scenarios"].keys()) == {s.id for s in SCENARIOS}
    for sid, per_side in rep["scenarios"].items():
        assert {"legacy", "langchain"} <= set(per_side.keys())
        assert len(per_side["legacy"]) == 2
        assert len(per_side["langchain"]) == 2
    # All 9 required categories are represented.
    categories = {s.category for s in SCENARIOS}
    assert len(categories) == 9


@pytest.mark.asyncio
async def test_legacy_replays_stable_across_whole_frozen_set():
    """The production (legacy) provider passes every frozen scenario across
    all repeats — no replay flakiness, no regression on any category."""
    rep = await run_full_bakeoff(reps=3)
    for sid, per_side in rep["scenarios"].items():
        stable, _any = _side_pass(per_side["legacy"])
        assert stable, f"legacy lost replay stability on scenario {sid}"


@pytest.mark.asyncio
async def test_legacy_is_never_worse_than_langchain():
    """Control-variable integrity: on every scenario legacy must be at least
    as good as LangChain (it may never lose where LangChain wins)."""
    rep = await run_full_bakeoff(reps=3)
    for sid, per_side in rep["scenarios"].items():
        legacy_ok, _ = _side_pass(per_side["legacy"])
        lc_ok, _ = _side_pass(per_side["langchain"])
        assert legacy_ok or not lc_ok, f"legacy failed {sid} while LangChain passed"


@pytest.mark.asyncio
async def test_decision_critical_gap_is_measured():
    """The gap that drives the decision is actually observed: Learn E2E and
    long-session continuity pass on legacy and fail on LangChain."""
    rep = await run_full_bakeoff(reps=3)
    for sid in ("learn_turn", "long_session_continuity"):
        legacy_ok, _ = _side_pass(rep["scenarios"][sid]["legacy"])
        lc_ok, _ = _side_pass(rep["scenarios"][sid]["langchain"])
        assert legacy_ok, f"legacy unexpectedly failed {sid}"
        assert not lc_ok, (
            f"LangChain unexpectedly passed {sid} — decision baseline may have shifted"
        )

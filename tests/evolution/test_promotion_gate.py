"""Promotion Gate tests — candidate can never directly reach production; the
gate is auditable and rollback-able."""

from __future__ import annotations

import pytest

from lumen.evolution.promotion_gate import (
    CandidateGate,
    GateDecision,
    GateStage,
    PromotionGate,
)


def _passing_judge(stage, candidate, context=None):
    return True


def _failing_judge(stage, candidate, context=None):
    return stage != GateStage.AB_TEST


@pytest.mark.asyncio
async def test_passing_candidate_reaches_promotion_decision():
    gate = CandidateGate("candidate-x", _passing_judge)
    decision = await gate.run()
    assert decision == GateDecision.PROMOTED
    assert gate.passed()


@pytest.mark.asyncio
async def test_failing_candidate_stops_and_never_promotes():
    gate = CandidateGate("cand-bad", _failing_judge)
    decision = await gate.run()
    assert decision == GateDecision.FAIL
    assert not gate.passed()


@pytest.mark.asyncio
async def test_gate_records_audit_trail():
    gate = CandidateGate("cand-an", _passing_judge)
    await gate.run()
    assert len(gate.audit_trail) == len(list(GateStage)) + 1  # all stage logs + final promotion log
    assert gate.audit_trail[-1]["stage"] == "promotion"


@pytest.mark.asyncio
async def test_promotion_gate_rejects_production_as_candidate():
    pg = PromotionGate(production_provider_id="legacy")
    with pytest.raises(ValueError):
        pg.register_candidate("legacy", _passing_judge)


@pytest.mark.asyncio
async def test_candidate_cannot_modify_production_provider_pointer():
    pg = PromotionGate(production_provider_id="legacy")
    cand = pg.register_candidate("cand-p", _passing_judge)
    await cand.run()
    cand.apply()
    # The gate's production pointer is immutable by the candidate.
    assert pg.production_provider_id == "legacy"


@pytest.mark.asyncio
async def test_rollback_supported():
    gate = CandidateGate("cand-rb", _passing_judge)
    await gate.run()
    assert gate.apply() == GateDecision.PROMOTED
    assert gate.rollback() == GateDecision.ROLLED_BACK

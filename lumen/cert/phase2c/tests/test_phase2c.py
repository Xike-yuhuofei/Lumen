"""Deterministic tests for Phase 2C: adaptive selector + promotion machinery.

No live LLM: the adaptive selector's *auditability* (it reads only public learner
signal), the anti-degeneration gate, and the adaptive-vs-fixed promotion decision
must be provably correct in isolation. The real multi-trial comparison is a
separate bounded run against the real Lumen LLM.
"""

from __future__ import annotations

import json

import pytest

from lumen.cert.models import CandidateManifest, content_digest
from lumen.cert.phase2.compare import run_episode
from lumen.cert.phase2.scenarios import BASELINE_STRATEGY_ID, load_real_base_prompt
from lumen.cert.phase2b.stability import PHASE2B_SCENARIOS
from lumen.cert.phase2c.adaptive import (
    ADAPTIVE_STRATEGY_ID,
    BASELINE,
    DIAGNOSE_FIRST,
    SOCRATIC,
    AdaptiveLumenTutor,
    AdaptiveStrategySelector,
    build_adaptive_candidate,
    strategy_directive,
    strategy_mix,
)
from lumen.cert.phase2c.decide import decide
from lumen.cert.store import CertificationStore

# ── Selector: public-signal auditability ─────────────────────────────────────

def _decide(text, turn=3):
    return AdaptiveStrategySelector().select(
        turn_index=turn, prior_conversation=[], learner_utterance=text
    )


def test_selector_opens_with_socratic():
    d = _decide("I want to learn Concurrency in Go.", turn=1)
    assert d.strategy_id == SOCRATIC
    assert d.turn_index == 1
    assert d.rationale and d.evidence


def test_selector_backchannel_elicits():
    assert _decide("ok", turn=4).strategy_id == SOCRATIC
    assert _decide("Got it. Where are we starting?", turn=3).strategy_id in (SOCRATIC, BASELINE)


def test_selector_strong_claim_triggers_diagnose_first():
    for claim in (
        "a bigger sample is always more accurate",
        "correlation proves causation",
        "the test is nearly perfect so the result must be right",
        "a positive result definitely means I have the condition",
        "goroutines are just lightweight threads",
        "a channel is basically a generic queue",
    ):
        d = _decide(claim, turn=3)
        assert d.strategy_id == DIAGNOSE_FIRST, claim
        assert "strong-claim marker in learner utterance" in d.evidence, claim


def test_selector_uncertain_or_neutral_is_default():
    # Negated / hedged phrasing must NOT fire the strong-claim branch.
    for text in (
        "I'm not sure about this one.",
        "I can't wait, let's keep going.",
        "That makes sense, what's next?",
        "Could you go over that again?",
    ):
        d = _decide(text, turn=4)
        assert d.strategy_id != DIAGNOSE_FIRST, text


def test_selector_never_touches_hidden_or_eval():
    # The selector signature only receives public dialogue — it has no access to
    # hidden/evaluator/diagnosis data by construction (compile-time guarantee).
    import inspect

    sig = inspect.signature(AdaptiveStrategySelector.select)
    params = set(sig.parameters)
    assert {"turn_index", "prior_conversation", "learner_utterance"} <= params
    assert "hidden" not in params and "evaluation" not in params and "diagnosis" not in params


def test_strategy_directive_maps_known_strategies():
    assert strategy_directive(DIAGNOSE_FIRST).startswith("STRATEGY:")
    assert strategy_directive(SOCRATIC).startswith("STRATEGY:")
    assert strategy_directive(BASELINE) == ""


# ── Adaptive candidate + mix ─────────────────────────────────────────────────


def test_adaptive_candidate_is_real_and_self_documenting():
    base = load_real_base_prompt("en")
    scen = PHASE2B_SCENARIOS["sampling-bias"]
    cand = build_adaptive_candidate(scenario=scen, base_prompt=base)
    assert cand.effective_candidate_id.startswith("p2c-")
    assert cand.tutor_config.get("strategy_tag") == ADAPTIVE_STRATEGY_ID
    assert "ADAPTIVE STRATEGY POLICY" in cand.prompt_override
    # policy is additive to the real base and bounded (regression wellformed-safe).
    assert len(cand.prompt_override) < len(base) + 4000
    payload = {"tutor_config": cand.tutor_config, "prompt_override": cand.prompt_override,
               "temperature": cand.temperature}
    assert cand.content_digest == content_digest(payload)


def test_strategy_mix_detects_degeneration():
    single = [{"strategy_id": SOCRATIC} for _ in range(9)] + [{"strategy_id": SOCRATIC}]
    m = strategy_mix(single)
    assert m["dominant_ratio"] == 1.0
    assert len([k for k in m["by_strategy"]]) == 1

    mixed = [{"strategy_id": SOCRATIC} for _ in range(5)] + [{"strategy_id": DIAGNOSE_FIRST} for _ in range(3)] + [{"strategy_id": BASELINE} for _ in range(2)]
    m2 = strategy_mix(mixed)
    assert m2["total"] == 10
    assert len([k for k in m2["by_strategy"]]) == 3
    assert m2["dominant_ratio"] < 1.0


# ── Adaptive runner (deterministic, ScriptedGateway) ─────────────────────────


def _go_blob():
    return {"evaluation_status": "VALID", "decision": "GO", "criterion_id": "next_action",
            "affected_turn": 1, "evidence": "clear", "severity": "minor",
            "reason": "acceptable", "confidence": 0.9}


@pytest.mark.asyncio
async def test_adaptive_episode_records_per_turn_decisions(tmp_path):
    from lumen.cert.llm import ScriptedGateway

    # Learner will voice a strong claim mid-episode; tutor script canned.
    go = json.dumps(_go_blob())
    script = {
        "tutor": ["Let me ask you a short question."] * 6,
        "learner": [
            "I want to learn statistics." if i == 0 else ("a bigger sample is always more accurate" if i == 2 else "ok")
            for i in range(6)
        ],
        "evaluator_correctness": [go] * 6,
        "evaluator_pedagogy": [go] * 6,
        "evaluator_context": [go] * 6,
    }
    gw = ScriptedGateway(script=script)
    store = CertificationStore(str(tmp_path / "p2c.db"))
    base = load_real_base_prompt("en")
    scen = PHASE2B_SCENARIOS["sampling-bias"]
    cand = build_adaptive_candidate(scenario=scen, base_prompt=base)
    tutor = AdaptiveLumenTutor(gw, candidate=cand, language="en")
    rep = await run_episode(
        gateway=gw, store=store, candidate=cand, scenario=scen,
        max_turns=4, clean_tool_io=True, tutor=tutor,
    )
    assert rep["strategy_id"] == ADAPTIVE_STRATEGY_ID
    dec = rep["strategy_decisions"]
    # turn1/2 opening, turn3 backchannel "ok", turn4 strong claim.
    assert len(dec) == 4
    assert {d["turn_index"] for d in dec} == {1, 2, 3, 4}
    assert any(d["strategy_id"] == DIAGNOSE_FIRST for d in dec), dec
    # "strategies actually used" recorded with rationale+evidence.
    for d in dec:
        assert d["rationale"] and d["evidence"]


# ── Promotion decision (deterministic) ───────────────────────────────────────


def _ad_cell(scen, pass_rate, trials, i, inner_mix=None):
    inner_mix = inner_mix or [{"strategy_id": s} for s in (SOCRATIC, DIAGNOSE_FIRST, BASELINE)]
    return {
        "scenario_id": scen, "strategy_id": ADAPTIVE_STRATEGY_ID, "pass_rate": pass_rate,
        "mean_confidence": 0.8, "all_pass": pass_rate == 1.0,
        "episode_status": "PASS" if pass_rate == 1.0 else "FAIL",
        "episode_id": f"ep-{scen}-adaptive-{trials}-{i}",
        "strategy_decisions": [dict(d) for d in inner_mix],
        "n_turns": len(inner_mix),
    }


def _fixed_cell(scen, strat, pass_rate, i):
    return {
        "scenario_id": scen, "strategy_id": strat, "pass_rate": pass_rate,
        "mean_confidence": 0.8, "all_pass": pass_rate == 1.0,
        "episode_status": "PASS" if pass_rate == 1.0 else "FAIL",
        "episode_id": f"ep-{scen}-{strat}-{i}",
        "strategy_decisions": [],
    }


def _cells_adaptive_wins():
    cells = []
    for scen in ("s1", "s2", "s3"):
        for i in range(3):
            cells.append(_fixed_cell(scen, "baseline", 0.4, i))
            cells.append(_fixed_cell(scen, "socratic-questions", 0.4, i))
            cells.append(_ad_cell(scen, 0.9, 3, i))
    return cells


def test_decide_promotes_adaptive_when_stable_with_gates():
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = decide(_cells_adaptive_wins(), gate=gate)
    assert d["decision"] == "PROMOTE ADAPTIVE CANDIDATE"
    assert d["promoted_candidates"] == [ADAPTIVE_STRATEGY_ID]
    assert d["better_than_best_fixed_scenarios"] == 3
    assert d["worse_than_baseline_scenarios"] == 0
    assert d["degenerate"] is False
    assert d["global_mean_pass_rate"]["adaptive"] > d["global_mean_pass_rate"]["baseline"]
    assert d["global_mean_pass_rate"]["adaptive"] > d["global_mean_pass_rate"]["socratic-questions"]


def test_decide_never_without_gates():
    d = decide(_cells_adaptive_wins(), gate=None)
    assert d["decision"] == "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"


def test_decide_rejects_single_lucky_trial():
    # best-fixed advantage vanishes once adaptive's best trial is dropped.
    cells = []
    for scen in ("s1", "s2"):
        for i in range(1):
            cells.append(_fixed_cell(scen, "baseline", 0.4, i))
            cells.append(_fixed_cell(scen, "socratic-questions", 0.4, i))
        cells.append(_ad_cell(scen, 1.0, 1, 0))  # only one adaptive trial
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = decide(cells, gate=gate)
    assert d["decision"] == "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"


def test_decide_rejects_degenerate_adaptive():
    # adaptive always picks socratic -> indistinguishable from fixed socratic.
    cells = []
    for scen in ("s1", "s2", "s3"):
        for i in range(3):
            cells.append(_fixed_cell(scen, "baseline", 0.4, i))
            cells.append(_fixed_cell(scen, "socratic-questions", 0.4, i))
            cells.append(_ad_cell(scen, 0.9, 3, i, inner_mix=[{"strategy_id": SOCRATIC} for _ in range(6)]))
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = decide(cells, gate=gate)
    assert d["degenerate"] is True
    assert d["decision"] == "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"


def test_decide_rejects_worse_than_baseline_anywhere():
    cells = []
    for scen in ("s1", "s2"):
        for i in range(3):
            cells.append(_fixed_cell(scen, "baseline", 0.4, i))
            cells.append(_fixed_cell(scen, "socratic-questions", 0.4, i))
            cells.append(_ad_cell(scen, 0.9, 3, i))
    # one scenario where adaptive (0.9) trails baseline (0.95)
    for i in range(3):
        cells.append(_fixed_cell("s3", "baseline", 0.95, i))
        cells.append(_fixed_cell("s3", "socratic-questions", 0.5, i))
        cells.append(_ad_cell("s3", 0.9, 3, i))
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = decide(cells, gate=gate)
    assert d["worse_than_baseline_scenarios"] == 1
    assert d["decision"] == "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"


__all__: list[str] = []
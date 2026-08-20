"""Deterministic tests for Phase 2B: Regression Contract + stability machinery.

No live LLM: the Phase 2B *contract* and *stability classifier* must be 
provably correct and un-game-able in isolation. The real multi-trial comparison
is a separate bounded run; these tests guarantee the classifier cannot promote a
candidate that is not stably better, and that the regression contract now tracks
the Frozen Baseline prompt instead of an inconsistent absolute cap.
"""

from __future__ import annotations

import json

import pytest

from lumen.cert.llm import ScriptedGateway
from lumen.cert.models import CandidateManifest
from lumen.cert.phase2.compare import strip_tool_io
from lumen.cert.phase2.scenarios import BASELINE_STRATEGY_ID, build_candidate, load_real_base_prompt
from lumen.cert.phase2b.stability import (
    PHASE2B_SCENARIOS,
    SOCRATIC_STRATEGY_ID,
    aggregate_trials,
    stability_decide,
)
from lumen.cert.regression import (
    CANDIDATE_PROMPT_ADDITIVE_BUDGET,
    RegressionRunner,
    _check_candidate_wellformed,
)
from lumen.cert.store import CertificationStore
from lumen.cert.tutor import load_real_teaching_prompt

# ── Measurement fidelity: strip_tool_io ──────────────────────────────────────


def test_strip_tool_io_removes_protocol_blocks_only():
    raw = (
        "```tool\nplan\n```\n```json\n{...json...}\n```\n\n"
        "Now let's think about the send on an unbuffered channel.\n\n"
        "```json\n{\"unrelated\": true}\n```\nfinal sentence."
    )
    cleaned = strip_tool_io(raw)
    assert "tool" not in cleaned and "json" not in cleaned and "{...json...}" not in cleaned
    assert "Now let's think about the send on an unbuffered channel." in cleaned
    assert "final sentence." in cleaned


def test_strip_tool_io_is_strategy_symmetric():
    # Applied identically to any arm's text — cannot manufacture an advantage.
    a = strip_tool_io("```tool\nx\n```\nQ: what is a channel?")
    b = strip_tool_io("```tool\nx\n```\nQ: what is a channel?")
    assert a == b == "Q: what is a channel?"


# ── Regression Contract (Baseline-relative) ──────────────────────────────────


def _candidate(prompt="", subject="Test", temp=0.2) -> CandidateManifest:
    import uuid

    from lumen.cert.models import content_digest

    cfg = {"subject": subject, "strategy_tag": "test"}
    return CandidateManifest(
        effective_candidate_id=f"p2b-test-{uuid.uuid4().hex[:8]}",
        parent_candidate_id=None,
        content_digest=content_digest({"tutor_config": cfg, "prompt_override": prompt, "temperature": temp}),
        tutor_config=cfg,
        prompt_override=prompt,
        temperature=temp,
    )


def test_regression_contract_lets_frozen_baseline_and_additive_candidate_pass():
    real_en = load_real_teaching_prompt("en")
    # Frozen Baseline uses the real prompt via empty override (Phase 1 behaviour).
    ok, note = _check_candidate_wellformed(_candidate(prompt=""), {"language": "en"})
    assert ok, note
    # A legitimate additive Candidate = real prompt + directive, larger than 4000.
    assert len(real_en) > 4000  # precondition: real prompt itself exceeds old cap
    directive = "STRATEGY: Question-driven (Socratic) teaching.\nAsk short questions."
    override = real_en + "\n\n" + directive
    ok, note = _check_candidate_wellformed(_candidate(prompt=override), {"language": "en"})
    assert ok, note
    # And it uses the additive budget, not the absolute 4000.
    assert len(override) > CANDIDATE_PROMPT_ADDITIVE_BUDGET


def test_regression_contract_still_blocks_unbounded_directive_bloat():
    real_en = load_real_teaching_prompt("en")
    # A candidate that grows the frozen prompt far beyond the additive budget fails.
    override = real_en + "\n\n" + ("X" * (CANDIDATE_PROMPT_ADDITIVE_BUDGET + 1))
    ok, note = _check_candidate_wellformed(_candidate(prompt=override), {"language": "en"})
    assert not ok
    assert "exceeds the Frozen Baseline prompt" in note


def test_builtin_regression_gate_now_passes_socratic_override(tmp_path):
    from lumen.cert.evaluators import build_evaluator_suite

    base = load_real_base_prompt("en")
    scen = PHASE2B_SCENARIOS["base-rate-neglect"]
    cand = build_candidate(strategy=SOCRATIC_STRATEGY_ID, scenario=scen, base_prompt=base)
    gw = ScriptedGateway(script={})
    store = CertificationStore(str(tmp_path / "p2b.db"))
    runner = RegressionRunner(gw, store, evaluators_factory=lambda: [])
    results = runner.deterministic(cand, {"language": "en"})
    by_id = {r.case_id: r.passed for r in results}
    # The exact gate that blocked Phase 2A promotion now passes for socratic.
    assert by_id["reg-candidate-wellformed"] is True
    assert by_id["reg-real-teaching-prompt"] is True


# ── Stability aggregation + decision ─────────────────────────────────────────


def _cell(scen, strat, pass_rate, conf=0.8, all_pass=None, i=0):
    if all_pass is None:
        all_pass = pass_rate == 1.0
    return {
        "scenario_id": scen, "strategy_id": strat, "pass_rate": pass_rate,
        "mean_confidence": conf, "all_pass": all_pass,
        "episode_status": "PASS" if all_pass else "FAIL",
        "episode_id": f"ep-{scen}-{strat}-{i}",
        "effective_candidate_id": f"p2b-{scen}-{strat}-{i}",
        "no_go_total": 0,
    }


def _agg_from_cells(cells):
    return aggregate_trials(cells)


def test_aggregate_trials_groups_and_averages():
    cells = [
        _cell("s1", "baseline", 0.5, i=0), _cell("s1", "baseline", 0.7, i=1),
        _cell("s1", "socratic-questions", 0.9, i=0), _cell("s1", "socratic-questions", 1.0, i=1),
        _cell("s2", "baseline", 0.4, i=0), _cell("s2", "socratic-questions", 0.8, i=0),
    ]
    a = _agg_from_cells(cells)
    assert a["s1"]["baseline"]["n_trials"] == 2
    assert a["s1"]["baseline"]["mean_pass_rate"] == 0.6
    assert a["s1"]["socratic-questions"]["mean_pass_rate"] == 0.95
    assert a["s2"]["socratic-questions"]["n_trials"] == 1


def test_decide_rejects_single_lucky_trial():
    # socratic better here only because one trial is 1.0; dropping its best trial
    # it is no better than baseline -> "better_unstable", so not a stable better.
    cells = [
        _cell("s1", "baseline", 0.4, i=0), _cell("s1", "baseline", 0.4, i=1),
        _cell("s1", "socratic-questions", 1.0, all_pass=True, i=0),
        _cell("s1", "socratic-questions", 0.4, i=1),  # mean 0.7, trimmed(0.4)=0.4 !> 0.4
    ]
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = stability_decide(_agg_from_cells(cells), gate=gate)
    assert d["per_scenario"]["s1"]["verdict"] == "better_unstable"
    assert d["decision"] == "KEEP BASELINE / CONTINUE EXPERIMENT"


def test_decide_requires_multi_scenario():
    # Only one scenario (s1) is robustly better; need >= MIN_SCENARIOS_BETTER.
    cells = [
        _cell("s1", "baseline", 0.4, i=0), _cell("s1", "socratic-questions", 0.9, i=0),
        _cell("s1", "socratic-questions", 0.9, i=1),
    ]
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = stability_decide(_agg_from_cells(cells), gate=gate)
    assert d["better_scenarios"] == 1
    assert d["decision"] == "KEEP BASELINE / CONTINUE EXPERIMENT"


def test_decide_promotes_when_stable_across_scenarios_with_gates():
    cells = []
    for scen in ("s1", "s2"):
        cells += [_cell(scen, "baseline", 0.4, i=0), _cell(scen, "baseline", 0.4, i=1)]
        cells += [_cell(scen, "socratic-questions", 0.9, i=0), _cell(scen, "socratic-questions", 0.9, i=1)]
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = stability_decide(_agg_from_cells(cells), gate=gate)
    assert d["better_scenarios"] == 2 and d["worse_scenarios"] == 0
    assert d["decision"] == "PROMOTE CANDIDATE"
    assert d["promoted_candidates"] == ["socratic-questions"]


def test_decide_never_promotes_without_gates():
    cells = []
    for scen in ("s1", "s2"):
        cells += [_cell(scen, "baseline", 0.4, i=0), _cell(scen, "baseline", 0.4, i=1)]
        cells += [_cell(scen, "socratic-questions", 0.9, i=0), _cell(scen, "socratic-questions", 0.9, i=1)]
    d = stability_decide(_agg_from_cells(cells), gate=None)  # metrics alone are never enough
    assert d["decision"] == "KEEP BASELINE / CONTINUE EXPERIMENT"


def test_decide_rejects_worse_anywhere():
    cells = [
        _cell("s1", "baseline", 0.4, i=0), _cell("s1", "socratic-questions", 0.9, i=0),
        _cell("s1", "socratic-questions", 0.9, i=1),
        _cell("s2", "baseline", 0.9, i=0), _cell("s2", "socratic-questions", 0.4, i=0),  # worse
    ]
    gate = {"replay_pass": True, "regression_pass": True, "phase1_certification_pass": True}
    d = stability_decide(_agg_from_cells(cells), gate=gate)
    assert d["worse_scenarios"] == 1
    assert d["decision"] == "KEEP BASELINE / CONTINUE EXPERIMENT"


# ── strip_tool_io wiring through run_episode (end-to-end, ScriptedGateway) ───


def _go_blob():
    return {
        "evaluation_status": "VALID", "decision": "GO",
        "criterion_id": "next_action", "affected_turn": 1,
        "evidence": "clear next step", "severity": "minor",
        "reason": "acceptable teaching behaviour", "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_run_episode_strips_tool_io_for_evaluation_only(tmp_path):
    from lumen.cert.phase2.compare import run_episode
    from lumen.cert.phase2b.stability import PHASE2B_SCENARIOS

    go = json.dumps(_go_blob())
    tutor_with_tool = "```tool\nplan\n```\n```json\n{}\n```\nLet's start with a short question: what do you think a goroutine is?"
    script = {
        "tutor": [tutor_with_tool] * 6,
        "learner": ["I think it's like a thread."] * 6,
        "evaluator_correctness": [go] * 6,
        "evaluator_pedagogy": [go] * 6,
        "evaluator_context": [go] * 6,
    }
    gw = ScriptedGateway(script=script)
    store = CertificationStore(str(tmp_path / "p2b.db"))
    base = "base"
    scen = PHASE2B_SCENARIOS["base-rate-neglect"]
    cand = build_candidate(strategy="baseline", scenario=scen, base_prompt=base)
    rep = await run_episode(
        gateway=gw, store=store, candidate=cand, scenario=scen,
        max_turns=3, clean_tool_io=True,
    )
    # Raw (tool-bearing) action is stored in the trace...
    stored = store.get_turns(rep["episode_id"])
    assert "tool" in stored[0]["tutor_action"]
    # ...but with strip_tool_io=True the all-GO script yields all PASS (the evaluator
    # judged the cleaned teaching prose, not the protocol JSON).
    assert rep["all_pass"] is True
    assert rep["no_go_total"] == 0


__all__: list[str] = []
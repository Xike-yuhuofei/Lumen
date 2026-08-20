"""Deterministic tests for the Phase 2A Teaching Strategy Optimisation machinery.

These prove the *machinery* (scenario registry, candidate identity, comparison
runner, decision rules) without a live LLM, using the Phase 1
``lumen.cert.ScriptedGateway``. The real, discriminating strategy comparison is
a separate bounded run against the real Lumen LLM; these tests guarantee the
comparator and decider do not silently game or weaken any gate.
"""

from __future__ import annotations

import json

import pytest

from lumen.cert.llm import ScriptedGateway
from lumen.cert.models import CandidateManifest, content_digest
from lumen.cert.store import CertificationStore

from lumen.cert.phase2.scenarios import (
    BASELINE_STRATEGY_ID,
    SCENARIOS,
    STRATEGY_ORDER,
    STRATEGIES,
    build_candidate,
    join_prompt,
    load_real_base_prompt,
)
from lumen.cert.phase2.compare import run_episode
from lumen.cert.phase2.decide import KEEP, PROMOTE, decide, compare_vs_baseline


# ── Scenario / strategy registry ─────────────────────────────────────────────


@pytest.mark.parametrize("sid", list(SCENARIOS.keys()))
def test_scenario_is_wellformed_and_discriminating(sid):
    scen = SCENARIOS[sid]
    cfg = scen["tutor_config"]
    assert scen["id"]
    assert cfg["subject"].strip()
    assert cfg["goal"].strip()
    assert len(cfg["knowledge_points"]) >= 3
    profile = cfg["learner_profile"]
    assert "misconception" in profile or "assumption" in profile
    # Profile must be able to make the tutor adapt (diagnosis / correction axis).
    assert "1-3 sentences" in profile


def test_strategy_order_baseline_first():
    assert STRATEGY_ORDER[0] == BASELINE_STRATEGY_ID
    assert set(STRATEGY_ORDER) == set(STRATEGIES.keys())
    # Baseline has no directive (uses the real prompt) — controlled variable.
    assert STRATEGIES[BASELINE_STRATEGY_ID]["directive"] == ""


def test_candidate_identity_changes_with_strategy_and_scenario():
    base = "You are Lumen, a real mastery tutor." 
    c_b = build_candidate(strategy="baseline", scenario=SCENARIOS["go-concurrency"], base_prompt=base)
    c_d = build_candidate(strategy="diagnose-first", scenario=SCENARIOS["go-concurrency"], base_prompt=base)
    c_s = build_candidate(strategy="socratic-questions", scenario=SCENARIOS["sampling-bias"], base_prompt=base)
    # New strategy / scenario -> new effective id, never overwrite.
    assert len({c_b.effective_candidate_id, c_d.effective_candidate_id, c_s.effective_candidate_id}) == 3
    # Baseline uses the real prompt (empty override); candidates carry real+directive.
    assert c_b.prompt_override == ""
    assert "STRATEGY:" in c_d.prompt_override
    assert c_b.temperature == c_d.temperature == 0.2
    # digest matches the content-digest of the manifest payload.
    payload = {"tutor_config": c_d.tutor_config, "prompt_override": c_d.prompt_override,
               "temperature": c_d.temperature}
    assert c_d.content_digest == content_digest(payload)


def test_join_prompt_additive_only():
    base = "real prompt"
    assert join_prompt(base, "") == ""
    assert join_prompt(base, "x").startswith("real prompt")
    assert join_prompt("", "x") == "x"


def test_real_base_prompt_loads():
    text = load_real_base_prompt("en")
    assert text.strip()  # the real Lumen mastery prompt must still load


# ── Comparison runner (deterministic, ScriptedGateway) ───────────────────────


def _go_script() -> dict[str, list[str]]:
    """A gateway script where every role returns an all-GO judgment."""
    go = json.dumps(_go_blob())
    return {
        "tutor": ["Let's break this down. First, what do you already think about it?"] * 12,
        "learner": ["I think I get it."] * 12,
        "evaluator_correctness": [go] * 12,
        "evaluator_pedagogy": [go] * 12,
        "evaluator_context": [go] * 12,
    }


def _go_blob() -> dict:
    return {
        "evaluation_status": "VALID",
        "decision": "GO",
        "criterion_id": "next_action",
        "affected_turn": 1,
        "evidence": "the tutor gives a clear next step",
        "severity": "minor",
        "reason": "acceptable teaching behaviour",
        "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_run_episode_all_go(tmp_path):
    gw = ScriptedGateway(script=_go_script())
    store = CertificationStore(str(tmp_path / "p2a.db"))
    scen = SCENARIOS["go-concurrency"]
    cand = build_candidate(strategy="diagnose-first", scenario=scen, base_prompt="base")
    rep = await run_episode(gateway=gw, store=store, candidate=cand, scenario=scen, max_turns=10)
    assert rep["all_pass"] is True
    assert rep["pass_rate"] == 1.0
    assert rep["n_turns"] == 10
    assert rep["no_go_total"] == 0 and rep["invalid_total"] == 0
    assert rep["episode_status"] == "PASS"
    # Trajectory/eval context ids are stable per scenario (fair comparison).
    assert rep["effective_candidate_id"] == cand.effective_candidate_id
    assert len(store.get_turns(rep["episode_id"])) == 10
    assert len(store.get_evaluations(rep["episode_id"])) == 30


@pytest.mark.asyncio
async def test_run_episode_no_go_is_recorded_not_promoted(tmp_path):
    script = _go_script()
    # One turn yields a NO_GO (a native teaching failure) — must not be launder.
    script["evaluator_correctness"][2] = json.dumps({
        **_go_blob(), "decision": "NO_GO", "criterion_id": "correctness",
        "reason": "misconception left unaddressed", "confidence": 0.5})
    gw = ScriptedGateway(script=script)
    store = CertificationStore(str(tmp_path / "p2a.db"))
    scen = SCENARIOS["go-concurrency"]
    cand = build_candidate(strategy="baseline", scenario=scen, base_prompt="base")
    rep = await run_episode(gateway=gw, store=store, candidate=cand, scenario=scen, max_turns=10)
    assert rep["all_pass"] is False
    assert rep["n_fail"] == 1
    assert rep["no_go_total"] == 1
    assert rep["episode_status"] == "FAIL"
    assert rep["per_turn"][2]["final_status"] == "FAIL"


@pytest.mark.asyncio
async def test_run_episode_invalid_is_unresolved_not_pass(tmp_path):
    script = _go_script()
    script["evaluator_context"] = []  # no canned response -> LLMCallError -> INVALID
    gw = ScriptedGateway(script=script)
    store = CertificationStore(str(tmp_path / "p2a.db"))
    scen = SCENARIOS["sampling-bias"]
    cand = build_candidate(strategy="socratic-questions", scenario=scen, base_prompt="base")
    rep = await run_episode(gateway=gw, store=store, candidate=cand, scenario=scen, max_turns=3)
    # Any INVALID forces UNRESOLVED — never counted as a pass or a failure.
    assert all(t["final_status"] == "UNRESOLVED" for t in rep["per_turn"])
    assert rep["all_pass"] is False and rep["n_fail"] == 0
    assert rep["invalid_total"] > 0
    assert rep["episode_status"] == "BLOCKED"


# ── Decision logic (deterministic) ───────────────────────────────────────────


def _cell(scen, strat, pass_rate, conf, all_pass=None):
    if all_pass is None:
        all_pass = pass_rate == 1.0
    return {"scenario_id": scen, "strategy_id": strat, "pass_rate": pass_rate,
            "mean_confidence": conf, "all_pass": all_pass,
            "episode_status": "PASS" if all_pass else "FAIL"}


def test_compare_vs_baseline_classification():
    base = _cell("s", "baseline", 1.0, 0.8, True)
    better_pr = _cell("s", "x", 1.0, 0.9, True)  # same pass, higher confidence
    worse = _cell("s", "x", 0.5, 0.8, False)
    assert compare_vs_baseline(better_pr, base)["verdict"] == "better"
    assert compare_vs_baseline(worse, base)["verdict"] == "worse"


def test_keep_when_no_evidence():
    matrix = [
        _cell("go-concurrency", "baseline", 1.0, 0.80, True),
        _cell("go-concurrency", "diagnose-first", 1.0, 0.82, True),
        _cell("sampling-bias", "baseline", 1.0, 0.8, True),
        _cell("sampling-bias", "diagnose-first", 1.0, 0.75, False),
    ]
    d = decide(matrix)
    assert d["decision"] == KEEP
    assert d["promoted_candidates"] == []


def test_candidate_needs_multi_scenario_and_gates_to_promote():
    # diagnose-first strictly better in BOTH scenarios, but gates are not passed.
    matrix = [
        _cell("go-concurrency", "baseline", 0.7, 0.8, False),
        _cell("go-concurrency", "diagnose-first", 1.0, 0.9, True),
        _cell("sampling-bias", "baseline", 0.6, 0.8, False),
        _cell("sampling-bias", "diagnose-first", 1.0, 0.88, True),
    ]
    d = decide(matrix)
    # Metrics favour it, but no gate evidence -> still KEEP.
    assert d["evaluations"]["diagnose-first"]["better_scenarios"] == 2
    assert d["decisions"]["diagnose-first"]["verdict"] == KEEP
    assert d["decision"] == KEEP


def test_promote_only_with_gates_and_stability():
    matrix = [
        _cell("go-concurrency", "baseline", 0.7, 0.8, False),
        _cell("go-concurrency", "diagnose-first", 1.0, 0.9, True),
        _cell("sampling-bias", "baseline", 0.6, 0.8, False),
        _cell("sampling-bias", "diagnose-first", 1.0, 0.88, True),
    ]
    gate = {"diagnose-first": {"replay_pass": True, "regression_pass": True,
                                "phase1_certification_pass": True}}
    d = decide(matrix, gate=gate)
    assert d["decision"] == PROMOTE
    assert d["promoted_candidates"] == ["diagnose-first"]


def test_promote_never_if_worse_anywhere():
    matrix = [
        _cell("go-concurrency", "baseline", 0.7, 0.8, False),
        _cell("go-concurrency", "socratic-questions", 1.0, 0.9, True),
        _cell("sampling-bias", "baseline", 0.8, 0.8, False),
        _cell("sampling-bias", "socratic-questions", 0.5, 0.9, False),  # worse here
    ]
    gate = {"socratic-questions": {"replay_pass": True, "regression_pass": True,
                                    "phase1_certification_pass": True}}
    d = decide(matrix, gate=gate)
    assert d["decision"] == KEEP
    assert d["decisions"]["socratic-questions"]["worse_scenarios"] == 1
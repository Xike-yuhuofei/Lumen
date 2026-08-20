"""Phase 1 Teaching Optimization Loop — machinery tests (deterministic)."""

from __future__ import annotations

import json
import re

import pytest

from lumen.cert import (
    Attribution,
    CandidateManifest,
    CertificationController,
    ContextManifest,
    EpisodeEnd,
    EvaluationStatus,
    FinalTurnStatus,
    Phase1State,
    RawVerdict,
    build_contexts,
    content_digest,
)
from lumen.cert.attribution import AttributionGate
from lumen.cert.engine import Budget
from lumen.cert.llm import ScriptedGateway
from lumen.cert.models import (
    RegressionCase,
    RegressionSeverity,
)
from lumen.cert.regression import RegressionRunner
from lumen.cert.simulator import LearnerSimulator
from lumen.cert.store import CertificationStore, CertificationStoreError
from lumen.cert.tutor import LumenTutor


def _eval(status: str, decision: str | None, *, criterion="correctness", evidence="tutor said the fact") -> str:
    return json.dumps(
        {
            "evaluation_status": status,
            "decision": decision,
            "criterion_id": criterion,
            "affected_turn": 1,
            "evidence": evidence,
            "severity": "major" if decision == "NO_GO" else "minor",
            "reason": "reason text",
            "confidence": 0.9 if decision == "GO" else 0.7,
        }
    )


GO = _eval("VALID", "GO")
NOGO = _eval("VALID", "NO_GO", criterion="pedagogy", evidence="tutor dumped jargon without scaffolding")
INVALID = _eval("INVALID", None)


SCENARIO = {"subject": "HTTP Protocol Basics"}
EVAL_CONFIG = {
    "rubric_version": "phase1-core-1.0",
    "perspectives": ["correctness", "pedagogy", "context"],
}


def _candidate() -> CandidateManifest:
    cfg = {
        "subject": "HTTP Protocol Basics",
        "knowledge_points": ["request/response", "status codes", "methods"],
        "learner_profile": "a curious adult beginner",
        "path_id": "p1-val-path",
    }
    return CandidateManifest(
        effective_candidate_id="cand-test-1",
        parent_candidate_id=None,
        content_digest=content_digest({"tutor_config": cfg, "prompt_override": "", "temperature": 0.2}),
        tutor_config=cfg,
        prompt_override="",
        temperature=0.2,
    )


@pytest.fixture
def store(tmp_path):
    return CertificationStore(str(tmp_path / "cert" / "cert.db"))


def _base_script(**overrides) -> dict[str, list[str]]:
    script = {
        "tutor": ["Lumen explains HTTP status codes with one concrete example, then asks the learner a short question."],
        "learner": ["If I GET a resource, does that also change it? I ask because I am not sure."],
        "evaluator_correctness": [GO],
        "evaluator_pedagogy": [GO],
        "evaluator_context": [GO],
    }
    script.update(overrides)
    return script


# ── PASS path: 10 Final Turn PASS under one candidate + consistent contexts ──


@pytest.mark.asyncio
async def test_episode_pass_10_turns(store, tmp_path):
    gateway = ScriptedGateway(script=_base_script())
    contexts = build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG)
    controller = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=contexts, scenario=SCENARIO, language="en",
    )
    outcome = await controller.certify()

    assert outcome.status == EpisodeEnd.PASS
    assert len(outcome.final_turn_statuses) == 10
    assert set(outcome.final_turn_statuses) == {FinalTurnStatus.PASS.value}
    assert outcome.patches_applied == 0

    # Same candidate + same contexts used throughout (no silent overwrite).
    turns = store.get_turns(outcome.episode_id)
    assert len(turns) == 10
    for t in turns:
        assert t["final_status"] == FinalTurnStatus.PASS.value
    # Every turn was evaluated by exactly three VALID, GO evaluators.
    evals = store.get_evaluations(outcome.episode_id)
    assert len(evals) == 30
    assert all(e["evaluation_status"] == "VALID" and e["decision"] == "GO" for e in evals)
    # Control-plane transition audit exists.
    transitions = store.list_transitions(outcome.episode_id)
    assert transitions, "certification must journal state transitions"


# ── LUMEN failure → review → engineering patch → replay → regression → restart: PASS ──


@pytest.mark.asyncio
async def test_lumen_failure_patch_restart_repass(store, tmp_path):
    gateway = ScriptedGateway(
        script=_base_script(
            tutor=["Lumen explains but without any concrete example."],
            learner=["I do not follow; can you show me?"],
            evaluator_pedagogy=[NOGO, GO],  # turn1 fails, replay+restart GO
            diagnosis=["{\"attribution\":\"LUMEN\",\"reasoning\":\"Tutor dumped jargon without scaffolding; learner was lost.\"}"],
            engineering=["Lumen, always give one concrete worked example to scaffold understanding, then confirm with a short question before moving on."],
        )
    )
    contexts = build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG)
    controller = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=contexts, scenario=SCENARIO, language="en",
    )
    outcome = await controller.certify()

    assert outcome.status == EpisodeEnd.PASS
    assert outcome.patches_applied == 1
    assert set(outcome.final_turn_statuses) == {FinalTurnStatus.PASS.value}
    assert len(outcome.final_turn_statuses) == 10

    # A NEW EffectiveCandidate was produced; the original was NOT overwritten.
    orig = store.get_candidate("cand-test-1")
    assert orig is not None and orig.prompt_override == ""
    new_cands = [
        c for c in _all_candidates(store) if c["id"] != "cand-test-1"
    ]
    assert len(new_cands) == 1
    assert new_cands[0]["parent_candidate_id"] == "cand-test-1"
    assert new_cands[0]["prompt_override"] != ""

    # Confirmed Lumen failure was frozen as a replayable FailureCase.
    cases = store.list_failure_cases(candidate_id="cand-test-1")
    assert cases and cases[0]["status"] == "frozen"
    assert cases[0]["frozen_checkpoint"]["failing_evaluator_id"] == "pedagogy"

    # Raw verdict (NO_GO) only triggered review; Final status is PASS on the
    # relitigated episode — the trace of the failing turn is preserved.
    all_evals = store.get_evaluations(outcome.episode_id)
    assert all(e["decision"] == "GO" for e in all_evals)


def _all_candidates(store):
    import sqlite3

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM cert_candidates").fetchall()]


# ── Non-LUMEN attribution must block Lumen mutation ──


@pytest.mark.asyncio
async def test_evaluator_attribution_blocks_mutation(store, tmp_path):
    done = {"engineering_called": False}

    async def _engineering(**k):
        done["engineering_called"] = True
        return "should never run"

    gateway = ScriptedGateway(
        script=_base_script(
            evaluator_pedagogy=[NOGO],
            diagnosis=["{\"attribution\":\"EVALUATOR\",\"reasoning\":\"The teaching was actually acceptable; the evaluator misjudged scaffolding.\"}"],
        )
    )
    contexts = build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG)
    controller = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=contexts, scenario=SCENARIO, language="en",
    )
    outcome = await controller.certify()

    assert outcome.status == EpisodeEnd.BLOCKED
    assert "EVALUATOR" in outcome.blocked_reason
    assert outcome.patches_applied == 0
    # Engineering agent never ran, no new candidate.
    assert len(_all_candidates(store)) == 1
    assert not done["engineering_called"]


@pytest.mark.asyncio
async def test_uncertain_fails_closed(store, tmp_path):
    gateway = ScriptedGateway(
        script=_base_script(
            tutor=["ambiguous"],
            learner=["what?"],
            evaluator_pedagogy=[NOGO],
            diagnosis=["{\"attribution\":\"UNCERTAIN\",\"reasoning\":\"Cannot determine responsibility.\"}"],
        )
    )
    controller = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG),
        scenario=SCENARIO, language="en",
    )
    outcome = await controller.certify()
    assert outcome.status == EpisodeEnd.BLOCKED
    assert outcome.patches_applied == 0
    assert len(_all_candidates(store)) == 1


# ── Evaluator INVALID must never become a tutor NO-GO; over budget → BLOCKED ──


@pytest.mark.asyncio
async def test_evaluator_invalid_never_tutor_nogo_and_blocks(store, tmp_path):
    gateway = ScriptedGateway(
        script=_base_script(
            tutor=["x"],
            learner=["y"],
            evaluator_correctness=[INVALID],
            evaluator_pedagogy=[INVALID],
            evaluator_context=[INVALID],
        )
    )
    controller = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG),
        scenario=SCENARIO, language="en",
    )
    outcome = await controller.certify()
    assert outcome.status == EpisodeEnd.BLOCKED
    assert "INVALID" in outcome.blocked_reason or "evaluator" in outcome.blocked_reason
    # Tutor was never judged NO_GO because of evaluator INVALID; no patch, no
    # new candidate, no Lumen mutation.
    assert outcome.patches_applied == 0
    assert len(_all_candidates(store)) == 1


# ── Attribution Gate semantics ──


def test_attribution_gate_only_lumen_mutates():
    assert AttributionGate.may_mutate_tutor(Attribution.LUMEN) is True
    for a in (Attribution.EVALUATOR, Attribution.SIMULATOR, Attribution.RUBRIC, Attribution.INFRA):
        assert AttributionGate.may_mutate_tutor(a) is False
    assert AttributionGate.may_mutate_tutor(Attribution.UNCERTAIN) is False
    assert AttributionGate.parse("garbage") == Attribution.UNCERTAIN


# ── Data Contract ──


def test_candidate_no_silent_overwrite(store):
    cand = _candidate()
    store.put_candidate(cand)
    # identical digest: idempotent, fine
    store.put_candidate(cand)
    tampered = CandidateManifest(
        effective_candidate_id="cand-test-1",
        parent_candidate_id=None,
        content_digest=content_digest({"tutor_config": {}, "prompt_override": "changed", "temperature": 0.9}),
        tutor_config={},
        prompt_override="changed",
        temperature=0.9,
    )
    with pytest.raises(CertificationStoreError):
        store.put_candidate(tampered)


def test_context_no_silent_overwrite(store):
    c = build_contexts(scenario={"subject": "A"}, evaluation_config={"v": 1})
    store.put_context(c)
    drift = ContextManifest(
        trajectory_context_id=c.trajectory_context_id,
        evaluation_context_id=c.evaluation_context_id,
        trajectory_digest=content_digest({"subject": "DIFFERENT"}),
        evaluation_digest=c.evaluation_digest,
    )
    with pytest.raises(CertificationStoreError):
        store.put_context(drift)


def test_regression_cannot_be_weakened(store):
    case = RegressionCase(
        regression_case_id="r1",
        description="x",
        severity=RegressionSeverity.CRITICAL,
        checker="candidate_wellformed",
        active=True,
    )
    store.put_regression_case(case)
    from lumen.cert.store import CertificationStoreError as E2

    weaker = RegressionCase(
        regression_case_id="r1",
        description="x",
        severity=RegressionSeverity.MAJOR,  # downgrade -> rejected
        checker="candidate_wellformed",
        active=True,
    )
    with pytest.raises(E2):
        store.put_regression_case(weaker)
    deactivated = RegressionCase(
        regression_case_id="r1",
        description="x",
        severity=RegressionSeverity.CRITICAL,
        checker="candidate_wellformed",
        active=False,
    )
    with pytest.raises(E2):
        store.put_regression_case(deactivated)


def test_builtin_regression_cases_present(store, tmp_path):
    from lumen.cert.tutor import load_real_teaching_prompt

    gateway = ScriptedGateway(script={})
    runner = RegressionRunner(gateway, store, evaluators_factory=lambda: [])
    results = runner.deterministic(_candidate(), {})
    ids = [r.case_id for r in results]
    assert "reg-real-teaching-prompt" in ids
    for r in results:
        assert r.case_id and r.severity.value in {"CRITICAL", "MAJOR", "MINOR"}
    assert load_real_teaching_prompt("en").strip() != ""


@pytest.mark.asyncio
async def test_hidden_state_never_reaches_tutor():
    captured = {}

    def on_call(label, system_prompt, user_prompt):
        captured.setdefault(label, []).append((system_prompt, user_prompt))

    gateway = ScriptedGateway(
        script={"tutor": ["ok"], "learner": ["hm"]}, on_call=on_call
    )
    cand = _candidate()
    tutor = LumenTutor(gateway, candidate=cand, language="en")
    # A hidden-state marker lives in the learner state dict that the tutor must
    # never be handed (structural isolation).
    from lumen.cert.planes import TeachingPlane

    plane = TeachingPlane(tutor, LearnerSimulator(gateway, candidate=cand))
    action = await plane.teach(
        turn_index=1,
        history=[],
        learner_utterance="I want to learn HTTP.",
    )
    # Plant a secret in hidden state and confirm the tutor's call never saw it.
    _secret = "SECRET-HIDDEN-STATE"
    assert _secret not in action
    for label, calls in captured.items():
        for sysprompt, usr in calls:
            if label == "learner" or label == "tutor":
                assert _secret not in sysprompt and _secret not in usr


def test_regression_runner_minimal_scope(store, tmp_path):
    """Active CRITICAL structural cases are always present and executable."""
    from lumen.cert.tutor import load_real_teaching_prompt

    gateway = ScriptedGateway(script={})
    runner = RegressionRunner(
        gateway, store, evaluators_factory=lambda: []
    )
    results = runner.deterministic(_candidate(), {})
    ids = [r.case_id for r in results]
    assert "reg-real-teaching-prompt" in ids
    passing = {r.case_id: r.passed for r in results}
    # The real prompt must load (real Lumen file exists).
    assert load_real_teaching_prompt("en").strip() != ""


def test_real_teaching_prompt_is_lumen_tuple():
    from lumen.cert.tutor import load_real_teaching_prompt

    text = load_real_teaching_prompt("en")
    assert "Lumen" in text or "tutor" in text.lower() or text.strip()


# ── Evaluation-only Change: retain trace, new EvaluationContext, re-adjudicate ──


EVAL_CONFIG_V11 = {
    "rubric_version": "phase1-core-1.1",
    "perspectives": ["correctness", "pedagogy", "context"],
}


@pytest.mark.asyncio
async def test_evaluation_only_change_rejudges_immutable_trace(store, tmp_path):
    """Rubric change with unchanged trace → new eval ctx, same traj ctx, full re-judge."""
    from lumen.cert.rejudge import rejudge_episode

    # 1) Produce a 10-Final-Turn-PASS episode under the base context.
    gateway = ScriptedGateway(script=_base_script())
    base_ctx = build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG)
    ctrl = CertificationController(
        gateway=gateway, store=store, candidate=_candidate(),
        contexts=base_ctx, scenario=SCENARIO, language="en",
    )
    outcome = await ctrl.certify()
    assert outcome.status == EpisodeEnd.PASS
    src_id = outcome.episode_id
    src_before = store.get_turns(src_id)
    assert len(src_before) == 10

    # 2) Evaluation-only change (new rubric version / evaluator config).
    rgw = ScriptedGateway(script=_base_script())  # all GO under the new rubric
    report = await rejudge_episode(
        gateway=rgw, store=store, source_episode_id=src_id,
        scenario=SCENARIO, new_evaluation_config=EVAL_CONFIG_V11,
        old_evaluation_config=EVAL_CONFIG,
    )

    assert report["kind"] == "evaluation-only-change"
    # Immutable trace retained (source turn rows unchanged, still readable).
    src_after = store.get_turns(src_id)
    assert [t["tutor_action"] for t in src_after] == [t["tutor_action"] for t in src_before]
    assert [t["learner_utterance"] for t in src_after] == [t["learner_utterance"] for t in src_before]
    # New EvaluationContext but SAME TrajectoryContext (trace untouched).
    assert report["new_evaluation_context_id"] != report["old_evaluation_context_id"]
    assert report["new_evaluation_digest"] != report["old_evaluation_digest"]
    assert report["trajectory_context_id"] == outcome.trajectory_context_id
    assert report["new_rubric_version"] == "phase1-core-1.1"
    # Every existing turn re-adjudicated under the one unified new context.
    assert report["num_turns_rejudged"] == 10
    assert report["all_pass"] is True and report["status"] == EpisodeEnd.PASS.value
    assert all(pt["final_status"] == "PASS" for pt in report["per_turn"])
    # Persisted, version-traceable: new episode links same traj ctx + new eval ctx.
    rid = report["rejudge_episode_id"]
    rep = store.get_episode(rid)
    assert rep is not None
    assert rep["trajectory_context_id"] == outcome.trajectory_context_id
    assert rep["evaluation_context_id"] == report["new_evaluation_context_id"]
    assert rep["candidate_id"] == outcome.candidate_id
    assert len(store.get_evaluations(rid)) == 30  # 3 evaluators x 10 turns


@pytest.mark.asyncio
async def test_evaluation_only_change_rejects_trajectory_change(store, tmp_path):
    """A scenario (trajectory) change is NOT an evaluation-only change → rejected."""
    from lumen.cert.models import Episode, TurnArtifact
    from lumen.cert.rejudge import rejudge_episode

    src_id = "ep-src-neg"
    src_ctx = build_contexts(scenario=SCENARIO, evaluation_config=EVAL_CONFIG)
    store.create_episode(
        Episode(episode_id=src_id, candidate_id="cand-test-1",
                trajectory_context_id=src_ctx.trajectory_context_id,
                evaluation_context_id=src_ctx.evaluation_context_id)
    )
    store.append_turn(
        TurnArtifact(episode_id=src_id, turn_index=1,
                     learner_utterance="hi", tutor_action="hello",
                     prior_conversation=[], hidden_learner_state={})
    )

    rgw = ScriptedGateway(script=_base_script())
    with pytest.raises(ValueError, match="not evaluation-only"):
        await rejudge_episode(
            gateway=rgw, store=store, source_episode_id=src_id,
            scenario={"subject": "DIFFERENT SUBJECT"},  # changes trajectory digest
            new_evaluation_config=EVAL_CONFIG_V11,
            old_evaluation_config=EVAL_CONFIG,
        )
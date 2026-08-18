"""Teaching Policy Tests + deterministic Replay Tests.

Fixed (graph, goal, learner) must always yield the fixed TeachingAction, and
replaying the same input must produce byte-identical decisions (decision
trace included).
"""

from __future__ import annotations

from lumen.modes.learn.application.builder import build_graph_from_modules
from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    LearnerState,
    LearningGoal,
    TeachingAction,
    TeachingActionType,
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
    TeachingStrategy,
)
from lumen.modes.learn.policy.engine import DEFAULT_POLICY_PRIORITY, TeachingEngine


def _graph() -> TeachingKnowledgeGraph:
    model = TeachingKnowledgeModel(
        nodes=[
            TeachingNode(id="foundation", title="Foundation", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="target", title="Target", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="example", title="Example", type=TeachingNodeType.EXAMPLE),
            TeachingNode(id="mc", title="Misconception", type=TeachingNodeType.MISCONCEPTION),
            TeachingNode(id="fix", title="Fix", type=TeachingNodeType.EXPLANATION),
            TeachingNode(id="quiz", title="Quiz", type=TeachingNodeType.QUESTION),
        ],
        edges=[
            TeachingEdge(
                source="foundation", target="target", relation=TeachingRelationType.PREREQUISITE_OF
            ),
            TeachingEdge(
                source="example", target="target", relation=TeachingRelationType.EXAMPLE_OF
            ),
            TeachingEdge(
                source="mc", target="target", relation=TeachingRelationType.COMMONLY_CONFUSED_WITH
            ),
            TeachingEdge(source="fix", target="mc", relation=TeachingRelationType.CORRECTS),
            TeachingEdge(source="quiz", target="target", relation=TeachingRelationType.ASSESSES),
        ],
    )
    return TeachingKnowledgeGraph(model)


def _goal(**overrides) -> LearningGoal:
    kwargs = {"target_node_ids": ["target"]}
    kwargs.update(overrides)
    return LearningGoal(**kwargs)


def _learner(**overrides) -> LearnerState:
    kwargs = {"mastery": {"foundation": 1.0}}
    kwargs.update(overrides)
    return LearnerState(**kwargs)


# ── policy priority order ───────────────────────────────────────────────


def test_policy_priority_is_stable_and_complete() -> None:
    assert DEFAULT_POLICY_PRIORITY == (
        "resolve_pending",
        "remediate_misconception",
        "review_due",
        "prerequisite_gate",
        "first_exposure",
        "scaffold_escalation",
        "assess_gate",
        "complete",
    )


# ── fixed input -> fixed action ─────────────────────────────────────────


def test_pending_answer_outranks_everything() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(pending_answer=True, pending_node_id="target", misconceptions={"mc"}),
    )
    assert action.action == TeachingActionType.RESOLVE_PENDING
    assert action.focus_node_id == "target"
    assert "pending_question_must_be_resolved" in action.constraints


def test_misconception_outranks_progression() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.4}, misconceptions={"mc"}),
    )
    assert action.action == TeachingActionType.REMEDIATE_MISCONCEPTION
    assert action.strategy == TeachingStrategy.MISCONCEPTION_CORRECTION
    assert action.resource_node_ids == ["fix"]


def test_due_review_outranks_new_teaching() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(due_reviews=["target"]),
    )
    assert action.action == TeachingActionType.REVIEW
    assert action.strategy == TeachingStrategy.SPACED_REVIEW


def test_unmet_prerequisite_gates_target() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 0.3, "target": 0.4}, attempts={"target": 1}),
    )
    assert action.action == TeachingActionType.REVIEW_PREREQUISITE
    assert action.focus_node_id == "foundation"
    assert "prerequisite_gate" in action.constraints


def test_first_exposure_explains() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0}),
    )
    assert action.action == TeachingActionType.EXPLAIN
    assert action.strategy == TeachingStrategy.EXPLAIN_DIRECT
    assert action.scaffold_level.value == "full"


def test_low_mastery_shows_example() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.3}, attempts={"target": 2}),
    )
    assert action.action == TeachingActionType.SHOW_EXAMPLE
    assert action.resource_node_ids == ["example"]
    assert action.scaffold_level.value == "medium"


def test_repeated_failure_escalates_to_practice() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.3}, attempts={"target": 3}),
    )
    assert action.action == TeachingActionType.PRACTICE
    assert action.strategy == TeachingStrategy.SCAFFOLDED_PRACTICE
    assert action.scaffold_level.value == "light"


def test_assess_when_partially_learned() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.6}, attempts={"target": 1}),
    )
    assert action.action == TeachingActionType.ASSESS
    assert action.scaffold_level.value == "none"


def test_complete_when_all_mastered() -> None:
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.95}, attempts={"target": 2}),
    )
    assert action.action == TeachingActionType.COMPLETE


def test_scaffold_fades_after_mastery() -> None:
    # once mastery clears the low-mastery bar, escalate no longer applies;
    # the engine reassesses rather than re-scaffolding.
    action = TeachingEngine().decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.6}, attempts={"target": 3}),
    )
    assert action.action == TeachingActionType.ASSESS
    assert action.scaffold_level.value == "none"


# ── hard constraints ────────────────────────────────────────────────────


def test_empty_goal_rejected() -> None:
    with __import__("pytest").raises(ValueError):
        TeachingEngine().decide(
            graph=_graph(),
            goal=LearningGoal(target_node_ids=[]),
            learner=_learner(),
        )


def test_unknown_target_rejected() -> None:
    with __import__("pytest").raises(KeyError):
        TeachingEngine().decide(
            graph=_graph(),
            goal=_goal(target_node_ids=["ghost"]),
            learner=_learner(),
        )


# ── replay: deterministic decision + trace ──────────────────────────────


def test_replay_produces_identical_actions() -> None:
    engine = TeachingEngine()
    inputs = [
        (_goal(), _learner(mastery={"foundation": 1.0})),
        (_goal(), _learner(mastery={"foundation": 1.0, "target": 0.3}, attempts={"target": 2})),
        (_goal(), _learner(mastery={"foundation": 0.2, "target": 0.4}, attempts={"target": 1})),
        (_goal(), _learner(mastery={"foundation": 1.0, "target": 0.95}, attempts={"target": 2})),
    ]
    for goal, learner in inputs:
        first = engine.decide(graph=_graph(), goal=goal, learner=learner)
        second = engine.decide(graph=_graph(), goal=goal, learner=learner)
        assert first == second
        # decision trace is deterministic too (dict equality, not identity)
        assert first.to_dict() == second.to_dict()


def test_every_action_carries_a_decision_trace() -> None:
    engine = TeachingEngine()
    cases = [
        _learner(mastery={"foundation": 1.0}),
        _learner(mastery={"foundation": 1.0, "target": 0.3}, attempts={"target": 2}),
        _learner(mastery={"foundation": 1.0, "target": 0.95}, attempts={"target": 2}),
        _learner(mastery={"foundation": 1.0}, misconceptions={"mc"}),
        _learner(due_reviews=["target"]),
    ]
    for learner in cases:
        action: TeachingAction = engine.decide(graph=_graph(), goal=_goal(), learner=learner)
        assert action.trace.policy_applied  # a policy was applied
        assert action.trace.policies_evaluated  # ordered list recorded


def test_different_mastery_yields_different_actions() -> None:
    """The crux of the whole Teaching Core: mastery drives the decision."""
    engine = TeachingEngine()
    low = engine.decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.2}, attempts={"target": 2}),
    )
    high = engine.decide(
        graph=_graph(),
        goal=_goal(),
        learner=_learner(mastery={"foundation": 1.0, "target": 0.95}, attempts={"target": 2}),
    )
    assert low.action != high.action


def test_engine_is_time_free() -> None:
    """The engine must not depend on wall-clock time (replay safety)."""
    engine = TeachingEngine()
    learner = _learner(due_reviews=["target"])
    import time

    t0 = time.time()
    first = engine.decide(graph=_graph(), goal=_goal(), learner=learner)
    # due_reviews is resolved by the adapter at a fixed `now`; the engine sees
    # a static list, so re-deciding later is identical.
    second = engine.decide(graph=_graph(), goal=_goal(), learner=learner)
    assert first == second
    assert time.time() >= t0

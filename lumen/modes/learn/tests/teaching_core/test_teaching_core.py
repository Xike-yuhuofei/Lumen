from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
from lumen.modes.learn.domain.teaching_models import (
    LearnerState,
    LearningGoal,
    TeachingActionType,
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
)
from lumen.modes.learn.policy.engine import TeachingEngine


def _graph() -> TeachingKnowledgeGraph:
    model = TeachingKnowledgeModel(
        nodes=[
            TeachingNode(
                id="foundation",
                title="Foundation",
                type=TeachingNodeType.CONCEPT,
            ),
            TeachingNode(
                id="target",
                title="Target",
                type=TeachingNodeType.CONCEPT,
            ),
            TeachingNode(
                id="example",
                title="Example",
                type=TeachingNodeType.EXAMPLE,
            ),
            TeachingNode(
                id="misconception",
                title="Common misconception",
                type=TeachingNodeType.MISCONCEPTION,
            ),
            TeachingNode(
                id="correction",
                title="Correction",
                type=TeachingNodeType.EXPLANATION,
            ),
        ],
        edges=[
            TeachingEdge(
                source="foundation",
                target="target",
                relation=TeachingRelationType.PREREQUISITE_OF,
            ),
            TeachingEdge(
                source="example",
                target="target",
                relation=TeachingRelationType.EXAMPLE_OF,
            ),
            TeachingEdge(
                source="correction",
                target="misconception",
                relation=TeachingRelationType.CORRECTS,
            ),
        ],
    )
    return TeachingKnowledgeGraph(model)


def test_prerequisite_blocks_target() -> None:
    decision = TeachingEngine().decide(
        graph=_graph(),
        goal=LearningGoal(target_node_ids=["target"]),
        learner=LearnerState(
            mastery={"foundation": 0.2, "target": 0.4},
            attempts={"target": 1},
        ),
    )
    assert decision.action == TeachingActionType.REVIEW_PREREQUISITE
    assert decision.focus_node_id == "foundation"


def test_misconception_has_highest_priority() -> None:
    decision = TeachingEngine().decide(
        graph=_graph(),
        goal=LearningGoal(target_node_ids=["target"]),
        learner=LearnerState(
            mastery={"foundation": 1.0},
            misconceptions={"misconception"},
        ),
    )
    assert decision.action == TeachingActionType.REMEDIATE_MISCONCEPTION
    assert decision.resource_node_ids == ["correction"]


def test_low_mastery_uses_example() -> None:
    decision = TeachingEngine().decide(
        graph=_graph(),
        goal=LearningGoal(target_node_ids=["target"]),
        learner=LearnerState(
            mastery={"foundation": 1.0, "target": 0.3},
            attempts={"target": 2},
        ),
    )
    assert decision.action == TeachingActionType.SHOW_EXAMPLE
    assert decision.resource_node_ids == ["example"]


def test_complete_when_goal_is_mastered() -> None:
    decision = TeachingEngine().decide(
        graph=_graph(),
        goal=LearningGoal(target_node_ids=["target"], mastery_threshold=0.8),
        learner=LearnerState(
            mastery={"foundation": 1.0, "target": 0.9},
            attempts={"target": 2},
        ),
    )
    assert decision.action == TeachingActionType.COMPLETE


def test_prerequisite_cycle_is_detected() -> None:
    graph = _graph()
    graph.add_edge(
        TeachingEdge(
            source="target",
            target="foundation",
            relation=TeachingRelationType.PREREQUISITE_OF,
        )
    )
    try:
        graph.topological_order()
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("expected prerequisite cycle error")

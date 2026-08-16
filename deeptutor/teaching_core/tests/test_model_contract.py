"""Model Contract Tests for the Teaching Knowledge Model.

These verify that the canonical domain objects are stable, serialisable, and
version-tolerant: they are the data contract the rest of the Teaching Core
(and any future storage swap) depends on.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.teaching_core.models import (
    AssessmentResult,
    DecisionTrace,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    LearnerState,
    LearningGoal,
    LearningPlan,
    MasteryEstimate,
    SourceReference,
    TeachingAction,
    TeachingActionType,
    TeachingEdge,
    TeachingKnowledgeModel,
    TeachingNode,
    TeachingNodeType,
    TeachingRelationType,
    TeachingStrategy,
)

# ── canonical schema stability ──────────────────────────────────────────


def test_teaching_node_contract_fields() -> None:
    node = TeachingNode(
        id="n1",
        title="Derivatives",
        type=TeachingNodeType.CONCEPT,
        content="...",
        source_refs=["book#ch3"],
        difficulty=0.4,
        importance=0.9,
        teachability=0.8,
        metadata={"inferred": True},
    )
    dumped = node.model_dump(mode="json")
    assert dumped["id"] == "n1"
    assert dumped["type"] == "concept"
    assert dumped["difficulty"] == 0.4
    # round-trip survives the canonical shape
    restored = TeachingNode.model_validate(dumped)
    assert restored == node


def test_teaching_edge_contract_fields() -> None:
    edge = TeachingEdge(
        source="n1",
        target="n2",
        relation=TeachingRelationType.PREREQUISITE_OF,
        weight=0.9,
        metadata={"reason": "inferred"},
    )
    assert TeachingEdge.model_validate(edge.model_dump(mode="json")) == edge


def test_node_rejects_blank_ids() -> None:
    with pytest.raises(ValueError):
        TeachingNode(id="  ", title="X", type=TeachingNodeType.CONCEPT)
    with pytest.raises(ValueError):
        TeachingNode(id="n1", title="", type=TeachingNodeType.CONCEPT)


def test_node_rejects_out_of_range_metadata() -> None:
    with pytest.raises(ValueError):
        TeachingNode(id="n1", title="X", type=TeachingNodeType.CONCEPT, difficulty=1.5)
    with pytest.raises(ValueError):
        TeachingNode(id="n1", title="X", type=TeachingNodeType.CONCEPT, importance=-0.1)


def test_extra_fields_are_ignored_for_version_tolerance() -> None:
    # A future version may add fields; old consumers must not crash on them.
    raw = {
        "id": "n1",
        "title": "X",
        "type": "concept",
        "future_field": "ignored",
    }
    node = TeachingNode.model_validate(raw)
    assert node.id == "n1"
    assert "future_field" not in node.model_dump()


# ── the model rejects structurally invalid graphs ───────────────────────


def test_model_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValueError):
        TeachingKnowledgeModel(
            nodes=[
                TeachingNode(id="a", title="A", type=TeachingNodeType.CONCEPT),
                TeachingNode(id="a", title="A2", type=TeachingNodeType.CONCEPT),
            ]
        )


def test_model_rejects_dangling_edges() -> None:
    with pytest.raises(ValueError):
        TeachingKnowledgeModel(
            nodes=[TeachingNode(id="a", title="A", type=TeachingNodeType.CONCEPT)],
            edges=[
                TeachingEdge(source="a", target="missing", relation=TeachingRelationType.PART_OF)
            ],
        )


# ── SourceReference ─────────────────────────────────────────────────────


def test_source_reference_ref() -> None:
    ref = SourceReference(source_id="book", locator="ch3.2")
    assert ref.ref() == "book#ch3.2"
    ref_no_locator = SourceReference(source_id="book")
    assert ref_no_locator.ref() == "book"


def test_source_reference_rejects_blank_source() -> None:
    with pytest.raises(ValueError):
        SourceReference(source_id="")


# ── planning / learner / assessment contracts ───────────────────────────


def test_learning_goal_thresholds() -> None:
    goal = LearningGoal(target_node_ids=["a", "b"])
    assert goal.mastery_threshold == 0.8
    with pytest.raises(ValueError):
        LearningGoal(target_node_ids=["a"], mastery_threshold=1.2)


def test_learning_plan_holds_goals() -> None:
    plan = LearningPlan(id="p1", goals=[LearningGoal(target_node_ids=["a"])])
    assert plan.goals[0].target_node_ids == ["a"]


def test_learner_state_validation() -> None:
    with pytest.raises(ValueError):
        LearnerState(mastery={"a": 1.5})
    with pytest.raises(ValueError):
        LearnerState(attempts={"a": -1})


def test_mastery_estimate_is_not_an_assessment_result() -> None:
    estimate = MasteryEstimate(node_id="a", score=0.5, mastered=False)
    result = AssessmentResult(node_id="a", is_correct=True, mastery_after=0.5)
    # They are distinct types with different fields by design.
    assert set(estimate.model_dump()) != set(result.model_dump())
    # An assessment result can be turned into evidence (it is one datapoint).
    assert result.to_evidence().kind == EvidenceType.QUIZ_ANSWER
    assert result.to_evidence().outcome is True


def test_evidence_bundle_filters_by_node() -> None:
    bundle = EvidenceBundle(
        items=[
            EvidenceItem(node_id="a", kind=EvidenceType.QUIZ_ANSWER, outcome=True),
            EvidenceItem(node_id="a", kind=EvidenceType.QUIZ_ANSWER, outcome=False),
            EvidenceItem(node_id="b", kind=EvidenceType.QUIZ_ANSWER, outcome=True),
        ]
    )
    assert bundle.count("a") == 2
    assert bundle.count("a", kind=EvidenceType.QUIZ_ANSWER) == 2
    assert bundle.count("b") == 1
    assert len(bundle.for_node("a")) == 2


# ── TeachingAction contract ─────────────────────────────────────────────


def test_teaching_action_full_contract() -> None:
    action = TeachingAction(
        action=TeachingActionType.EXPLAIN,
        focus_node_id="n1",
        strategy=TeachingStrategy.EXPLAIN_DIRECT,
        scaffold_level="full",
        expected_evidence=EvidenceType.FEYNMAN_EXPLANATION,
        success_condition="learner explains n1",
        reason="first exposure",
        resource_node_ids=["n2"],
        constraints=["mastery_gate"],
        trace=DecisionTrace(policy_applied="first_exposure"),
    )
    d = action.to_dict()
    assert d["action"] == "explain"
    assert d["target_node_id"] == "n1"
    assert d["strategy"] == "explain_direct"
    assert d["trace"]["policy_applied"] == "first_exposure"
    # aliases agree
    assert action.target_node_id == action.focus_node_id
    # JSON-serialisable for the tool result channel
    json.dumps(d)


def test_teaching_action_serialisation_roundtrip() -> None:
    action = TeachingAction(
        action=TeachingActionType.REVIEW,
        focus_node_id="n1",
        strategy=TeachingStrategy.SPACED_REVIEW,
    )
    restored = TeachingAction.model_validate(action.model_dump(mode="json"))
    assert restored == action


def test_teaching_action_type_covers_required_behaviours() -> None:
    expected = {
        "remediate_misconception",
        "resolve_pending",
        "review",
        "review_prerequisite",
        "explain",
        "show_example",
        "practice",
        "assess",
        "complete",
    }
    assert expected <= {t.value for t in TeachingActionType}


def test_relation_type_covers_required_teaching_edges() -> None:
    expected = {
        "prerequisite_of",
        "part_of",
        "depends_on",
        "example_of",
        "contrasts_with",
        "explains",
        "supports",
        "commonly_confused_with",
        "remediates",
        "prepares_for",
    }
    assert expected <= {t.value for t in TeachingRelationType}

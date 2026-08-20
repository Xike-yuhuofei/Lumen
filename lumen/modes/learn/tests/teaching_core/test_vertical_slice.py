"""Vertical Slice Integration Test.

This is the canonical "real learning material" test that demonstrates the
Teaching Core's closed loop:

1. A learning path is created (via the existing LearningStore).
2. The TeachingService builds a Teaching Knowledge Graph from it.
3. The Teaching Engine decides the next TeachingAction.
4. The action is mapped to an instruction via the adapter.
5. After simulated learning (mastery bump), the engine re-decides differently.
6. The TeachingAction varies deterministically because of Knowledge Graph
   structure, mastery estimates, and learner state — not because of randomness
   or LLM calls.
"""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from lumen.modes.learn.adapters.learner_state import (
    action_instruction,
    goal_from_progress,
    learner_state_from_progress,
)
from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.application.builder import build_graph_from_modules
from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
    QuizAttempt,
)
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
    TeachingStrategy,
)
from lumen.modes.learn.policy.engine import TeachingEngine


@pytest.fixture
def temp_store_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _build_modules() -> list[LearningModule]:
    """A realistic 3-module learning path (like a "functions" chapter)."""
    return [
        LearningModule(
            id="path_m0",
            name="What is a Function",
            order=0,
            knowledge_points=[
                KnowledgePoint(
                    id="path_m0_kp0",
                    name="Definition of a Function",
                    type=KnowledgeType.CONCEPT,
                    module_id="path_m0",
                ),
                KnowledgePoint(
                    id="path_m0_kp1",
                    name="Function Notation",
                    type=KnowledgeType.MEMORY,
                    module_id="path_m0",
                ),
            ],
        ),
        LearningModule(
            id="path_m1",
            name="Evaluating Functions",
            order=1,
            knowledge_points=[
                KnowledgePoint(
                    id="path_m1_kp0",
                    name="Evaluate f(x)",
                    type=KnowledgeType.PROCEDURE,
                    module_id="path_m1",
                ),
                KnowledgePoint(
                    id="path_m1_kp1",
                    name="Domain and Range",
                    type=KnowledgeType.CONCEPT,
                    module_id="path_m1",
                ),
            ],
        ),
        LearningModule(
            id="path_m2",
            name="Function Composition",
            order=2,
            knowledge_points=[
                KnowledgePoint(
                    id="path_m2_kp0",
                    name="Compose Functions",
                    type=KnowledgeType.PROCEDURE,
                    module_id="path_m2",
                ),
            ],
        ),
    ]


def _teacher_graph() -> TeachingKnowledgeGraph:
    """A richer teaching graph with relations beyond the structural module graph.

    This is what an extracted teaching model would look like — with
    misconceptions, examples, and corrections wired in.
    """
    g = build_graph_from_modules(_build_modules(), source_id="path")
    # Add a misconception about domain
    g.add_node(
        TeachingNode(
            id="mc_domain",
            title="Domain is all real numbers",
            type=TeachingNodeType.MISCONCEPTION,
        )
    )
    g.add_edge(
        TeachingEdge(
            source="mc_domain",
            target="path_m1_kp1",
            relation=TeachingRelationType.COMMONLY_CONFUSED_WITH,
        )
    )
    # Add a correction explanation
    g.add_node(
        TeachingNode(
            id="fix_domain",
            title="Domain depends on the function",
            type=TeachingNodeType.EXPLANATION,
        )
    )
    g.add_edge(
        TeachingEdge(
            source="fix_domain",
            target="mc_domain",
            relation=TeachingRelationType.CORRECTS,
        )
    )
    # Add an example for composition
    g.add_node(
        TeachingNode(
            id="ex_comp",
            title="f(g(x)) with g(x)=x+1, f(x)=x^2",
            type=TeachingNodeType.EXAMPLE,
        )
    )
    g.add_edge(
        TeachingEdge(
            source="ex_comp",
            target="path_m2_kp0",
            relation=TeachingRelationType.EXAMPLE_OF,
        )
    )
    # Add an assessment question for function definition
    g.add_node(
        TeachingNode(
            id="q_def",
            title="Which of these is a function?",
            type=TeachingNodeType.QUESTION,
        )
    )
    g.add_edge(
        TeachingEdge(
            source="q_def",
            target="path_m0_kp0",
            relation=TeachingRelationType.ASSESSES,
        )
    )
    return g


def test_vertical_slice_full_loop() -> None:
    """Demonstrate the complete closed loop from start to finish.

    This is ONE test — it tells the story of a learner moving through the
    material, with the Teaching Engine's decisions changing at each step.
    """
    # ═══════════════ 1. SETUP ═══════════════════════════════════════════
    engine = TeachingEngine()
    graph = _teacher_graph()
    modules = _build_modules()

    # Create a LearningProgress as the existing system would.
    progress = LearningProgress(book_id="math-functions")
    progress.modules = list(modules)
    progress.knowledge_types = {kp.id: kp.type for m in modules for kp in m.knowledge_points}

    # ═══════════════ 2. FIRST DECISION ══════════════════════════════════
    # Fresh learner: no mastery, no attempts, no misconceptions.
    learner = learner_state_from_progress(progress, graph=graph)
    goal = goal_from_progress(progress, graph=graph)
    action1 = engine.decide(graph=graph, goal=goal, learner=learner)

    # The engine should start with the first unmastered target.
    # Since foundation prereqs are met (no prereqs for the first kp),
    # and there are no attempts, it should be "first_exposure" → EXPLAIN.
    assert action1.action == TeachingActionType.EXPLAIN
    assert action1.focus_node_id == "path_m0_kp0"  # first KP in module order
    assert action1.strategy == TeachingStrategy.EXPLAIN_DIRECT
    instruction1 = action_instruction(
        action1, node_title="Definition of a Function", node_type="concept"
    )
    assert instruction1["mastery_tool"] == "mastery_assess"
    assert "Definition of a Function" in instruction1["instruction"]
    # Quantitative EXPLAIN routes the first-check through mastery_quiz.
    instruction_quiz = action_instruction(action1, node_type="principle")
    assert instruction_quiz["mastery_tool"] == "mastery_quiz"
    assert action1.trace.policy_applied == "first_exposure"

    # ═══════════════ 3. AFTER LEARNING (first kp mastered) ═════════════
    # Simulate: the learner demonstrated understanding of the first concept.
    progress.qualitative_mastery["path_m0_kp0"] = True
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="q1",
            knowledge_point_id="path_m0_kp0",
            module_id="path_m0",
            is_correct=True,
        )
    )
    learner = learner_state_from_progress(progress, graph=graph)
    action2 = engine.decide(graph=graph, goal=goal, learner=learner)

    # The first kp is mastered, so the engine should move to the next.
    # The next is path_m0_kp1 (Function Notation, memory type).
    # First exposure: no attempts yet → EXPLAIN.
    assert action2.focus_node_id == "path_m0_kp1"
    assert action2.action == TeachingActionType.EXPLAIN

    # ═══════════════ 4. AFTER QUIZ FAILURE ON FUNCTION NOTATION ═════════
    # Simulate: the learner just attempted and failed the notation quiz.
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="q2",
            knowledge_point_id="path_m0_kp1",
            module_id="path_m0",
            is_correct=False,
        )
    )
    learner = learner_state_from_progress(progress, graph=graph)
    action3 = engine.decide(graph=graph, goal=goal, learner=learner)

    # Now there's 1 attempt, mastery is below low_mastery (0.5), so
    # scaffold_escalation applies with attempts <= 2 → SHOW_EXAMPLE (fallback
    # to explain since no example is linked to path_m0_kp1).
    # Actually, since there's no example linked to path_m0_kp1, and attempts=1,
    # the engine should fall to EXPLAIN with MEDIUM scaffold.
    assert action3.action == TeachingActionType.EXPLAIN
    assert action3.scaffold_level.value == "medium"

    # ═══════════════ 5. AFTER MISCONCEPTION ARISES ON DOMAIN ═════════════
    # Simulate: the learner advances to Domain & Range (path_m1_kp1) and
    # develops a misconception.
    # Mark path_m0_kp1 as mastered first.
    progress.qualitative_mastery["path_m0_kp1"] = True
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="q3",
            knowledge_point_id="path_m0_kp1",
            module_id="path_m0",
            is_correct=True,
        )
    )
    # Simulate: the misconception is active (error record).
    from lumen.modes.learn.domain.models import ErrorRecord, ErrorType, RetryAttempt

    progress.error_records.append(
        ErrorRecord(
            id="e1",
            question_id="q4",
            knowledge_point_id="mc_domain",
            module_id="path_m1",
            error_type=ErrorType.UNDERSTANDING_DEVIATION,
            status="active",
        )
    )
    learner = learner_state_from_progress(progress, graph=graph)
    action4 = engine.decide(graph=graph, goal=goal, learner=learner)

    # The misconception should outrank normal progression.
    assert action4.action == TeachingActionType.REMEDIATE_MISCONCEPTION
    assert action4.focus_node_id == "mc_domain"
    assert action4.strategy == TeachingStrategy.MISCONCEPTION_CORRECTION
    assert action4.resource_node_ids == ["fix_domain"]
    assert action4.trace.policy_applied == "remediate_misconception"

    # ═══════════════ 6. AFTER MISCONCEPTION RESOLVED ═════════════════════
    # Simulate: the misconception is resolved.
    progress.error_records[0].status = "graduated"
    learner = learner_state_from_progress(progress, graph=graph)
    action5 = engine.decide(graph=graph, goal=goal, learner=learner)

    # With misconception resolved, engine should progress. The next unmastered
    # target is path_m1_kp0 (Evaluate f(x), procedure type). No attempts yet.
    assert action5.focus_node_id == "path_m1_kp0"
    assert action5.action == TeachingActionType.EXPLAIN

    # ═══════════════ 7. COMPLETE WHEN ALL MASTERED ═══════════════════════
    # Simulate: the learner masters everything.
    mastered_ids = [kp.id for m in modules for kp in m.knowledge_points]
    for mid in mastered_ids:
        progress.qualitative_mastery[mid] = True
        progress.quiz_attempts.append(
            QuizAttempt(
                question_id=f"q_{mid}",
                knowledge_point_id=mid,
                module_id=mid.rsplit("_", 1)[0],
                is_correct=True,
            )
        )
    learner = learner_state_from_progress(progress, graph=graph)
    action6 = engine.decide(graph=graph, goal=goal, learner=learner)

    assert action6.action == TeachingActionType.COMPLETE
    assert action6.trace.policy_applied == "complete"

    # ═══════════════ 8. REPLAY VERIFICATION ═════════════════════════════
    # Every decision must be deterministic: replay the same inputs.
    states = [
        (learner_state_from_progress(progress, graph=graph), action6),
    ]
    for learner, expected_action in states:
        replayed = engine.decide(graph=graph, goal=goal, learner=learner)
        assert replayed == expected_action
        assert replayed.to_dict() == expected_action.to_dict()


def test_teaching_service_vertical_slice(tmp_path: Path) -> None:
    """Drive the vertical slice through the TeachingService facade with
    SQLite persistence, proving the persisted graph + engine decide
    deterministically and respond to new learner state."""
    from lumen.modes.learn.adapters.graph_repository import SQLiteTeachingGraphRepository
    from lumen.modes.learn.application.teaching_service import TeachingService

    store = LearningStore(root=tmp_path / "progress")
    repo = SQLiteTeachingGraphRepository(db_path=tmp_path / "graphs.db")

    progress = LearningProgress(book_id="vertical-slice")
    progress.modules = list(_build_modules())
    progress.knowledge_types = {
        kp.id: kp.type for m in progress.modules for kp in m.knowledge_points
    }
    store.save(progress)

    teaching = TeachingService(learning_store=store, graph_repository=repo)

    # 1. first decision: explain the first knowledge point
    action1 = teaching.decide("vertical-slice")
    assert action1.action == TeachingActionType.EXPLAIN
    assert action1.focus_node_id == "path_m0_kp0"

    # 2. the structural graph was built from modules and persisted to SQLite
    persisted = repo.load_graph("vertical-slice")
    assert persisted is not None
    assert persisted.has_node("path_m0_kp0")
    assert persisted.has_node("path_m1_kp0")

    # 3. learner masters the first kp -> engine moves on
    progress.qualitative_mastery["path_m0_kp0"] = True
    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="q1",
            knowledge_point_id="path_m0_kp0",
            module_id="path_m0",
            is_correct=True,
        )
    )
    store.save(progress)
    action2 = teaching.decide("vertical-slice")
    assert action2.focus_node_id == "path_m0_kp1"
    assert action2.action == TeachingActionType.EXPLAIN

    # 4. an extracted graph (with a misconception node) is persisted over the
    #    structural one; the misconception drives the next decision
    from lumen.modes.learn.domain.models import ErrorRecord, ErrorType

    extracted = _teacher_graph()
    repo.save_graph("vertical-slice", extracted)
    progress.error_records.append(
        ErrorRecord(
            id="e1",
            question_id="q4",
            knowledge_point_id="mc_domain",
            module_id="path_m1",
            error_type=ErrorType.UNDERSTANDING_DEVIATION,
            status="active",
        )
    )
    store.save(progress)

    # the stored graph is now the enriched one
    assert repo.load_graph("vertical-slice").has_node("mc_domain")

    # the active misconception drives the decision to remediation
    action3 = teaching.decide("vertical-slice")
    assert action3.action == TeachingActionType.REMEDIATE_MISCONCEPTION
    assert action3.focus_node_id == "mc_domain"
    assert action3.resource_node_ids == ["fix_domain"]

    # after the misconception is resolved, normal progression resumes
    progress.error_records[0].status = "graduated"
    store.save(progress)
    action4 = teaching.decide("vertical-slice")
    assert action4.focus_node_id == "path_m0_kp1"
    assert action4.action == TeachingActionType.EXPLAIN


def test_engine_differentiates_based_on_graph_structure() -> None:
    """Demonstrate that the graph structure drives different decisions.

    Two learners with the SAME mastery but different graph wiring should
    get different TeachingActions.
    """
    engine = TeachingEngine()

    # Graph A: simple linear chain, no examples, no assessments
    g_a = TeachingKnowledgeGraph(
        TeachingKnowledgeModel(
            nodes=[
                TeachingNode(id="a", title="A", type=TeachingNodeType.CONCEPT),
                TeachingNode(id="b", title="B", type=TeachingNodeType.CONCEPT),
            ],
            edges=[
                TeachingEdge(source="a", target="b", relation=TeachingRelationType.PREREQUISITE_OF),
            ],
        )
    )

    # Graph B: same chain but with a linked example
    g_b = TeachingKnowledgeGraph(
        TeachingKnowledgeModel(
            nodes=[
                TeachingNode(id="a", title="A", type=TeachingNodeType.CONCEPT),
                TeachingNode(id="b", title="B", type=TeachingNodeType.CONCEPT),
                TeachingNode(id="ex", title="Example", type=TeachingNodeType.EXAMPLE),
            ],
            edges=[
                TeachingEdge(source="a", target="b", relation=TeachingRelationType.PREREQUISITE_OF),
                TeachingEdge(source="ex", target="b", relation=TeachingRelationType.EXAMPLE_OF),
            ],
        )
    )

    learner = LearnerState(
        mastery={"a": 1.0, "b": 0.3},
        attempts={"b": 2},
    )
    goal = LearningGoal(target_node_ids=["b"])

    action_a = engine.decide(graph=g_a, goal=goal, learner=learner)
    action_b = engine.decide(graph=g_b, goal=goal, learner=learner)

    # Graph A has no example → scaffold_escalation falls back to EXPLAIN
    assert action_a.action == TeachingActionType.EXPLAIN
    # Graph B has an example → scaffold_escalation returns SHOW_EXAMPLE
    assert action_b.action == TeachingActionType.SHOW_EXAMPLE
    assert action_b.resource_node_ids == ["ex"]

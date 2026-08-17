"""Closed-loop regression tests for the Learn mastery loop.

Covers the loop-closure guarantees added in the Learn production pass:

1. **Single decision authority** — the TeachingEngine's mastery gates mirror
   ``policy.gate_threshold`` per knowledge type (0.9 quantitative, 1.0
   qualitative), so the engine reports COMPLETE exactly when
   ``policy.next_objective`` reports complete.
2. **Qualitative retention** — a qualitative pass seeds spaced repetition, so
   CONCEPT / DESIGN objectives re-enter the review queue.
3. **Misconception loop** — registered misconceptions become remediable graph
   nodes; a matched wrong answer blocks progression until remediated and the
   error record graduates.
4. **Source grounding** — knowledge-point descriptions / source refs travel
   onto the teaching graph.
5. **Explicit learning goal** — a scoped goal narrows both the tool gates and
   the engine's targets identically.
"""

from __future__ import annotations

import json
import time

import pytest

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    Misconception,
)
from deeptutor.learning.policy import (
    gate_threshold,
    map_summary,
    next_objective,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.teaching_core.adapters import (
    goal_from_progress,
    learner_state_from_progress,
)
from deeptutor.teaching_core.builder import build_graph_from_modules
from deeptutor.teaching_core.engine import TeachingEngine
from deeptutor.teaching_core.models import TeachingActionType, TeachingNodeType

# ── helpers ────────────────────────────────────────────────────────────────


def _modules(with_misconceptions: bool = False) -> list[LearningModule]:
    kps = [
        KnowledgePoint(
            id="path_m0_kp0",
            name="Function Notation",
            type=KnowledgeType.MEMORY,
            module_id="path_m0",
            description="How f(x) maps inputs to outputs",
            source_ref="textbook#ch1.2",
            misconceptions=(
                [
                    Misconception(
                        statement="f(x) means f times x",
                        correction="f is the function name; f(x) is the output for input x",
                    )
                ]
                if with_misconceptions
                else []
            ),
        ),
        KnowledgePoint(
            id="path_m0_kp1",
            name="Definition of a Function",
            type=KnowledgeType.CONCEPT,
            module_id="path_m0",
        ),
    ]
    return [LearningModule(id="path_m0", name="Functions", order=0, knowledge_points=kps)]


def _progress(with_misconceptions: bool = False) -> LearningProgress:
    progress = LearningProgress(book_id="path")
    # replace_modules never touches the store — a bare instance is enough.
    service = LearningService.__new__(LearningService)
    service.replace_modules(progress, _modules(with_misconceptions))
    return progress


def _decide(progress: LearningProgress):
    graph = build_graph_from_modules(progress.modules, source_id="path")
    learner = learner_state_from_progress(progress, graph=graph)
    goal = goal_from_progress(progress, graph=graph)
    return TeachingEngine().decide(graph=graph, goal=goal, learner=learner), graph


# ── 1. single decision authority ───────────────────────────────────────────


def test_engine_gate_matches_policy_gate_per_type():
    assert gate_threshold(KnowledgeType.MEMORY) == 0.9
    assert gate_threshold(KnowledgeType.PROCEDURE) == 0.9
    assert gate_threshold(KnowledgeType.CONCEPT) == 1.0
    assert gate_threshold(KnowledgeType.DESIGN) == 1.0


def _seen(progress: LearningProgress, kp_id: str, correct: bool) -> None:
    """Make an objective 'learning' (attempted) like a real quiz would."""
    from deeptutor.learning.models import QuizAttempt

    progress.quiz_attempts.append(
        QuizAttempt(
            question_id="q",
            knowledge_point_id=kp_id,
            module_id="path_m0",
            is_correct=correct,
        )
    )


def test_memory_below_tool_gate_is_not_complete_for_engine():
    """A MEMORY objective at 0.85 used to be COMPLETE for the engine (0.8
    default) but not mastered for the tools (0.9) — the loop-break this
    regression test pins down."""
    progress = _progress()
    progress.mastery_levels["path_m0_kp0"] = 0.85
    progress.knowledge_types["path_m0_kp0"] = KnowledgeType.MEMORY
    _seen(progress, "path_m0_kp0", correct=False)
    progress.qualitative_mastery["path_m0_kp1"] = True

    assert next_objective(progress).action == "practice"
    action, _ = _decide(progress)
    assert action.action != TeachingActionType.COMPLETE
    assert action.focus_node_id == "path_m0_kp0"


def test_engine_and_policy_agree_on_complete():
    progress = _progress()
    progress.mastery_levels["path_m0_kp0"] = 0.95
    progress.knowledge_types["path_m0_kp0"] = KnowledgeType.MEMORY
    _seen(progress, "path_m0_kp0", correct=True)
    progress.qualitative_mastery["path_m0_kp1"] = True

    assert next_objective(progress).action == "complete"
    action, _ = _decide(progress)
    assert action.action == TeachingActionType.COMPLETE


def test_qualitative_pass_but_partial_quantitative_keeps_engine_working():
    progress = _progress()
    progress.mastery_levels["path_m0_kp0"] = 1.0
    _seen(progress, "path_m0_kp0", correct=True)
    # Concept gate is qualitative (boolean) — quantitative 0.9 alone must not
    # clear it for either authority.
    progress.mastery_levels["path_m0_kp1"] = 0.9
    progress.knowledge_types["path_m0_kp1"] = KnowledgeType.CONCEPT
    _seen(progress, "path_m0_kp1", correct=False)

    assert next_objective(progress).action == "assess"
    action, _ = _decide(progress)
    assert action.action != TeachingActionType.COMPLETE


# ── 2. qualitative retention ───────────────────────────────────────────────


def test_qualitative_pass_seeds_spaced_repetition(tmp_path):
    from deeptutor.learning.storage import LearningStore

    service = LearningService(LearningStore(root=tmp_path))
    progress = service.get_or_create("path")
    service.replace_modules(progress, _modules())
    service.record_qualitative(
        progress,
        "path_m0_kp1",
        passed=True,
        evidence="explains mapping uniqueness",
        scheduler=SpacedRepetitionScheduler(),
    )

    assert "path_m0_kp1" in progress.repetition_states
    assert any(t.knowledge_point_id == "path_m0_kp1" for t in progress.review_queue)
    # The learner state projection surfaces the scheduled review.
    state = learner_state_from_progress(progress, now=time.time() + 40 * 86400)
    assert "path_m0_kp1" in state.due_reviews


# ── 3. misconception loop ──────────────────────────────────────────────────


def test_builder_materialises_misconceptions_and_grounding():
    graph = build_graph_from_modules(_modules(with_misconceptions=True), source_id="path")

    kp_node = graph.node("path_m0_kp0")
    assert kp_node.content == "How f(x) maps inputs to outputs"
    assert kp_node.source_refs == ["textbook#ch1.2"]

    mis_id = "path_m0_kp0__mis0"
    assert graph.has_node(mis_id)
    assert graph.node(mis_id).type == TeachingNodeType.MISCONCEPTION
    assert graph.node(mis_id).content == "f(x) means f times x"
    assert graph.node(mis_id).metadata["correction"].startswith("f is the function name")
    # the KP node is the correction resource for the misconception
    assert graph.resources_for(mis_id, "corrects") == ["path_m0_kp0"]


def test_matched_wrong_answer_forces_remediation_then_graduates(tmp_path):
    from deeptutor.learning.storage import LearningStore

    service = LearningService(LearningStore())
    progress = service.get_or_create("path")
    service.replace_modules(progress, _modules(with_misconceptions=True))

    mis_id = "path_m0_kp0__mis0"
    is_correct = service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="path_m0_kp0",
        module_id="path_m0",
        user_answer="f times x",
        expected_answer="the output value",
        question_type="short",
        scheduler=SpacedRepetitionScheduler(),
        misconception_node_id=mis_id,
    )
    assert not is_correct
    assert progress.error_records[0].misconception_node_id == mis_id

    graph = build_graph_from_modules(progress.modules, source_id="path")
    learner = learner_state_from_progress(progress, graph=graph)
    assert learner.misconceptions == {mis_id}

    goal = goal_from_progress(progress, graph=graph)
    action = TeachingEngine().decide(graph=graph, goal=goal, learner=learner)
    assert action.action == TeachingActionType.REMEDIATE_MISCONCEPTION
    assert action.focus_node_id == mis_id
    assert action.resource_node_ids == ["path_m0_kp0"]

    # A later correct answer graduates the error record and clears the gate.
    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="path_m0_kp0",
        module_id="path_m0",
        user_answer="the output value",
        expected_answer="the output value",
        question_type="short",
        scheduler=SpacedRepetitionScheduler(),
    )
    assert progress.error_records[0].status == "graduated"
    learner = learner_state_from_progress(progress, graph=graph)
    assert learner.misconceptions == set()


def test_misconception_match_is_server_side():
    from deeptutor.capabilities.mastery.tools import _match_misconception

    progress = _progress(with_misconceptions=True)
    assert _match_misconception(progress, "path_m0_kp0", "f(x) means f times x") == (
        "path_m0_kp0__mis0"
    )
    # Unrelated statement never matches; the model cannot forge node ids.
    assert _match_misconception(progress, "path_m0_kp0", "functions are graphs") == ""
    assert _match_misconception(progress, "path_m0_kp1", "f times x") == ""


# ── 4. explicit learning goal ──────────────────────────────────────────────


def test_goal_scope_narrows_both_authorities():
    progress = _progress()
    progress.goal_name = "notation only"
    progress.goal_kp_ids = ["path_m0_kp0"]
    progress.mastery_levels["path_m0_kp1"] = 0.2  # out of scope, ignored

    step = next_objective(progress)
    assert step.knowledge_point_id == "path_m0_kp0"

    progress.mastery_levels["path_m0_kp0"] = 0.95
    step = next_objective(progress)
    assert step.action == "complete"
    assert map_summary(progress)["complete"] is True

    graph = build_graph_from_modules(progress.modules, source_id="path")
    goal = goal_from_progress(progress, graph=graph)
    assert goal.target_node_ids == ["path_m0_kp0"]
    learner = learner_state_from_progress(progress, graph=graph)
    action = TeachingEngine().decide(graph=graph, goal=goal, learner=learner)
    assert action.action == TeachingActionType.COMPLETE


def test_goal_scope_stale_ids_are_dropped():
    progress = _progress()
    progress.goal_kp_ids = ["gone_kp", "path_m0_kp0"]
    step = next_objective(progress)
    assert step.knowledge_point_id == "path_m0_kp0"


def test_prerequisite_of_scoped_target_still_gates():
    progress = _progress()
    progress.goal_kp_ids = ["path_m0_kp1"]  # kp1 depends on kp0 in module order
    graph = build_graph_from_modules(progress.modules, source_id="path")
    goal = goal_from_progress(progress, graph=graph)
    learner = learner_state_from_progress(progress, graph=graph)
    action = TeachingEngine().decide(graph=graph, goal=goal, learner=learner)
    # The engine must teach the unmastered prerequisite first, even though it
    # is outside the goal scope.
    assert action.action == TeachingActionType.REVIEW_PREREQUISITE
    assert action.focus_node_id == "path_m0_kp0"


# ── 5. tool-level closed loop (build → plan → quiz → grade → remediate) ────


@pytest.fixture
def isolated_path(tmp_path, monkeypatch):
    from deeptutor.learning.storage import LearningStore

    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    monkeypatch.setattr(
        "lumen.modes.learn.adapters.graph_repository.default_graph_db_path",
        lambda: tmp_path / "graphs.db",
    )
    return "tool_path"


@pytest.mark.asyncio
async def test_tool_loop_diagnoses_misconception_and_plan_remediates(isolated_path):
    from deeptutor.tools.mastery_tool import (
        MasteryBuildTool,
        MasteryGoalTool,
        MasteryGradeTool,
        MasteryQuizTool,
        MasteryStatusTool,
        TeachingPlanTool,
    )

    build = await MasteryBuildTool().execute(
        _mastery_path_id=isolated_path,
        modules=[
            {
                "name": "Functions",
                "knowledge_points": [
                    {
                        "name": "Function Notation",
                        "type": "memory",
                        "description": "How f(x) maps inputs to outputs",
                        "source_ref": "textbook#ch1.2",
                        "misconceptions": [
                            {
                                "statement": "f(x) means f times x",
                                "correction": "f is the function name; f(x) is the output",
                            }
                        ],
                    }
                ],
            }
        ],
    )
    assert build.success

    plan = json.loads((await TeachingPlanTool().execute(_mastery_path_id=isolated_path)).content)
    assert plan["focus"]["content"] == "How f(x) maps inputs to outputs"
    assert plan["focus"]["source_refs"] == ["textbook#ch1.2"]

    quiz = await MasteryQuizTool().execute(
        _mastery_path_id=isolated_path,
        knowledge_point_id="tool_path_m0_kp0",
        question="In f(x), what does the notation denote?",
        expected_answer="the output for input x",
    )
    assert quiz.success
    question_id = json.loads(quiz.content)["question_id"]

    graded = await MasteryGradeTool().execute(
        _mastery_path_id=isolated_path,
        answer="f multiplied by x",
        question_id=question_id,
        misconception="f(x) means f times x",
    )
    payload = json.loads(graded.content)
    assert payload["is_correct"] is False
    assert payload["misconception_recorded"] is True

    plan = json.loads((await TeachingPlanTool().execute(_mastery_path_id=isolated_path)).content)
    assert plan["decision"]["action"] == "remediate_misconception"
    assert plan["misconception"]["correction"].startswith("f is the function name")

    # A scoped goal narrows the tool-side objective cursor too.
    goal = await MasteryGoalTool().execute(
        _mastery_path_id=isolated_path, name="notation only", scope_kp_ids=["tool_path_m0_kp0"]
    )
    assert goal.success
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=isolated_path)).content)
    assert status["map"]["goal"]["name"] == "notation only"

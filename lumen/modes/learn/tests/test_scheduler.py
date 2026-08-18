import time

import pytest

from lumen.modes.learn.domain.models import (
    ErrorRecord,
    ErrorType,
    KnowledgeType,
    LearningProgress,
    RepetitionState,
    ReviewTask,
)
from lumen.modes.learn.policy.scheduler import INTERVAL_SEQUENCES, SpacedRepetitionScheduler


@pytest.fixture
def scheduler():
    return SpacedRepetitionScheduler()


# ── interval sequences ───────────────────────────────────────────────────


class TestIntervalSequences:
    def test_memory_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.MEMORY] == [0, 1, 3, 7, 14, 30, 60]

    def test_concept_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.CONCEPT] == [3, 7, 14, 30]

    def test_procedure_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.PROCEDURE] == [3, 7, 14]

    def test_design_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.DESIGN] == [14, 28]


# ── get_initial_state ────────────────────────────────────────────────────


class TestInitialState:
    def test_memory_initial(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        assert state.interval_index == 0
        assert state.consecutive_correct == 0
        assert state.consecutive_wrong == 0
        assert abs(state.next_review_at - time.time()) < 5

    def test_design_initial(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.DESIGN)
        assert state.interval_index == 0
        assert abs(state.next_review_at - time.time() - 14 * 86400) < 5


# ── schedule_next: correct advances ──────────────────────────────────────


class TestCorrectAdvances:
    def test_first_correct(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.interval_index == 1
        assert state.consecutive_correct == 1
        assert state.consecutive_wrong == 0

    def test_two_consecutive_skip(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1, cc=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=3, cc=0
        assert state.interval_index == 3
        assert state.consecutive_correct == 0


# ── schedule_next: wrong retreats ────────────────────────────────────────


class TestWrongRetreats:
    def test_wrong_decrements(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0
        assert state.interval_index == 0
        assert state.consecutive_wrong == 1
        assert state.consecutive_correct == 0

    def test_two_consecutive_wrong_resets(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0, cw=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0, cw resets
        assert state.consecutive_wrong == 0


# ── schedule_next: boundaries ────────────────────────────────────────────


class TestBoundaries:
    def test_cant_go_below_zero(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        assert state.interval_index == 0

    def test_cant_exceed_sequence(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state.interval_index = 6  # max for MEMORY
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.interval_index == 6


# ── different types ──────────────────────────────────────────────────────


class TestDifferentTypes:
    def test_design_first_correct(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.DESIGN)
        state = scheduler.schedule_next(state, KnowledgeType.DESIGN, True)
        assert state.interval_index == 1

    def test_concept_sequence(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.CONCEPT)
        state = scheduler.schedule_next(state, KnowledgeType.CONCEPT, True)
        assert state.interval_index == 1


# ── get_due_tasks ────────────────────────────────────────────────────────


class TestGetDueTasks:
    def test_returns_due_only(self, scheduler):
        now = time.time()
        state = RepetitionState(next_review_at=now - 10)
        task = ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=now - 10,
            priority=1,
            state=state,
        )
        lp = LearningProgress(book_id="b1", review_queue=[task])
        due = scheduler.get_due_tasks(lp)
        assert len(due) == 1

    def test_skips_future(self, scheduler):
        now = time.time()
        state = RepetitionState(next_review_at=now + 86400)
        task = ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=now + 86400,
            priority=1,
            state=state,
        )
        lp = LearningProgress(book_id="b1", review_queue=[task])
        due = scheduler.get_due_tasks(lp)
        assert len(due) == 0

    def test_sorted_by_priority(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.review_queue = [
            ReviewTask(
                id="r_low",
                knowledge_point_id="kp_low",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=5,
                state=RepetitionState(next_review_at=now - 10),
            ),
            ReviewTask(
                id="r_high",
                knowledge_point_id="kp_high",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=1,
                state=RepetitionState(next_review_at=now - 10),
            ),
        ]
        due = scheduler.get_due_tasks(lp)
        assert [t.id for t in due] == ["r_high", "r_low"]

    def test_respects_max_tasks(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.review_queue = [
            ReviewTask(
                id=f"r{i}",
                knowledge_point_id=f"kp{i}",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=i,
                state=RepetitionState(next_review_at=now - 10),
            )
            for i in range(8)
        ]
        due = scheduler.get_due_tasks(lp, max_tasks=3)
        assert len(due) == 3


# ── build_review_queue ───────────────────────────────────────────────────


def _mastered_lp(kp_id: str, kp_type: KnowledgeType) -> LearningProgress:
    """A progress where *kp_id* is in the module tree AND mastered — only
    mastered objectives are reviewable (build_review_queue skips the rest)."""
    from lumen.modes.learn.domain.models import KnowledgePoint, LearningModule

    lp = LearningProgress(book_id="b1")
    lp.modules = [
        LearningModule(
            id="m1",
            name="M",
            order=0,
            knowledge_points=[
                KnowledgePoint(id=kp_id, name=kp_id, type=kp_type, module_id="m1")
            ],
        )
    ]
    lp.knowledge_types[kp_id] = kp_type
    if kp_type in (KnowledgeType.CONCEPT, KnowledgeType.DESIGN):
        lp.qualitative_mastery[kp_id] = True
        lp.mastery_levels[kp_id] = 1.0
    else:
        lp.mastery_levels[kp_id] = 1.0  # clears the 0.9 quantitative gate
    return lp


class TestBuildReviewQueue:
    def test_error_records_get_priority_1(self, scheduler):
        now = time.time()
        lp = _mastered_lp("kp1", KnowledgeType.MEMORY)
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].priority == 1

    def test_non_error_kp_uses_type_priority(self, scheduler):
        now = time.time()
        lp = _mastered_lp("kp_design", KnowledgeType.DESIGN)
        lp.repetition_states["kp_design"] = RepetitionState(next_review_at=now)
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        # DESIGN has the lowest urgency -> largest priority number, never 1.
        assert tasks[0].priority == 5
        assert tasks[0].knowledge_type == KnowledgeType.DESIGN

    def test_graduated_error_does_not_promote_priority(self, scheduler):
        now = time.time()
        lp = _mastered_lp("kp1", KnowledgeType.CONCEPT)
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        # Only active/retrying error records boost priority to 1.
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
                status="graduated",
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].priority == 3  # CONCEPT type priority, not 1

    def test_retrying_error_promotes_priority(self, scheduler):
        now = time.time()
        lp = _mastered_lp("kp1", KnowledgeType.CONCEPT)
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
                status="retrying",
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert tasks[0].priority == 1

    def test_unmastered_kp_gets_no_review_task(self, scheduler):
        """Regression: content that is not mastered is never due for review."""
        from lumen.modes.learn.domain.models import KnowledgePoint, LearningModule

        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.modules = [
            LearningModule(
                id="m1",
                name="M",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp1", name="kp1", type=KnowledgeType.MEMORY, module_id="m1"
                    )
                ],
            )
        ]
        lp.knowledge_types["kp1"] = KnowledgeType.MEMORY
        lp.mastery_levels["kp1"] = 0.5  # below the 0.9 gate -> not mastered
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now - 10)
        assert scheduler.build_review_queue(lp) == []

    def test_defaults_missing_type_to_memory(self, scheduler):
        now = time.time()
        lp = _mastered_lp("kp1", KnowledgeType.MEMORY)
        lp.knowledge_types.pop("kp1")  # no type entry -> defaults to MEMORY
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].knowledge_type == KnowledgeType.MEMORY
        assert tasks[0].priority == 2

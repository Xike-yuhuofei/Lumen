"""Real-material E2E: the full Learn loop over 《种草》 study notes.

Drives the production tool surface (mastery_build / mastery_goal /
teaching_plan / mastery_quiz / mastery_grade / mastery_assess) with the
repo's real study material ``种草-道层面的经验哲学.md`` — objectives,
descriptions, source refs and misconceptions are all taken from that text
(the way the tutor would design them after reading it), then the learner
walks the whole loop:

build → explain → wrong answer + misconception → remediation → qualitative
gate → prerequisite-ordered progression → quantitative gate (3 unaided
correct) → transfer-typed design gate → due review → COMPLETE.

No LLM calls: every decision must come from the deterministic engine, and
each turn's decision must consume the state the previous turn wrote.
"""

from __future__ import annotations

import json
import time

import pytest

from lumen.modes.learn.adapters.storage import LearningStore

# The tutor's module design over the real material (sections -> objectives).
REAL_MODULES = [
    {
        "name": "种草的道",
        "knowledge_points": [
            {
                "name": "种草的核心命题",
                "type": "concept",
                "description": "种草不是说服用户购买，而是帮助用户发现并实现其向往的生活",
                "source_ref": "种草-道层面的经验哲学#核心命题",
                "misconceptions": [
                    {
                        "statement": "种草就是说服用户购买",
                        "correction": "种草是帮助用户发现并实现其向往的生活，而非说服购买",
                    }
                ],
            },
            {
                "name": "从卖产品转向理解人",
                "type": "concept",
                "description": "用户购买的不是产品本身，而是产品所代表的某种生活状态",
                "source_ref": "种草-道层面的经验哲学#1",
            },
            {
                "name": "真诚的三个条件",
                "type": "memory",
                "description": "产品确实解决问题；内容真实呈现体验；企业与用户利益基本一致",
                "source_ref": "种草-道层面的经验哲学#4",
                "misconceptions": [
                    {
                        "statement": "真诚只是一种传播风格",
                        "correction": "真诚是经营逻辑：产品、内容与实际体验不一致只是透支信任",
                    }
                ],
            },
            {
                "name": "种草是组织能力",
                "type": "design",
                "description": "种草要求产品、研发、供应链、服务和营销围绕同一用户体验协同",
                "source_ref": "种草-道层面的经验哲学#6",
            },
        ],
    }
]

KP = {
    0: "zhongcao_m0_kp0",
    1: "zhongcao_m0_kp1",
    2: "zhongcao_m0_kp2",
    3: "zhongcao_m0_kp3",
}


@pytest.fixture
def path(tmp_path, monkeypatch):
    from lumen.modes.learn.adapters.graph_repository import default_graph_db_path

    def _init(self, root_arg=None):
        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    monkeypatch.setattr(
        "lumen.modes.learn.adapters.graph_repository.default_graph_db_path",
        lambda: tmp_path / "graphs.db",
    )
    return "zhongcao"


async def _plan(path_id):
    from lumen.modes.learn.chat_tools import TeachingPlanTool

    raw = await TeachingPlanTool().execute(_mastery_path_id=path_id)
    return json.loads(raw.content)


async def _quiz_and_grade(
    path_id,
    kp_id,
    answer,
    *,
    expected="正确答案",
    misconception="",
    question_type="short",
):
    from lumen.modes.learn.chat_tools import MasteryGradeTool, MasteryQuizTool

    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question=f"关于 {kp_id} 的问题",
                expected_answer=expected,
                question_type=question_type,
            )
        ).content
    )
    return json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                answer=answer,
                question_id=quiz["question_id"],
                misconception=misconception,
            )
        ).content
    )


async def _assess(path_id, kp_id, passed):
    from lumen.modes.learn.chat_tools import MasteryAssessTool

    return json.loads(
        (
            await MasteryAssessTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                passed=passed,
                feedback="learners own explanation" if passed else "incomplete",
            )
        ).content
    )


@pytest.mark.asyncio
async def test_real_material_full_loop_to_complete(path):
    from lumen.modes.learn.chat_tools import MasteryBuildTool, MasteryGoalTool

    # ── 1. material → teaching knowledge model ───────────────────────────
    build = json.loads(
        (
            await MasteryBuildTool().execute(
                _mastery_path_id=path, modules=REAL_MODULES, mode="replace"
            )
        ).content
    )
    assert build["knowledge_points_added"] == 4

    goal = json.loads(
        (
            await MasteryGoalTool().execute(
                _mastery_path_id=path, name="掌握《种草》之道", scope_kp_ids=list(KP.values())
            )
        ).content
    )
    assert goal["goal"]["scope"] == "subset"

    # ── 2. first exposure: explain the core proposition ─────────────────
    plan = await _plan(path)
    assert plan["decision"]["action"] == "explain"
    assert plan["focus"]["node_id"] == KP[0]
    assert plan["focus"]["content"].startswith("种草不是说服用户购买")
    assert plan["focus"]["source_refs"] == ["种草-道层面的经验哲学#核心命题"]

    # ── 3. wrong answer exposes the registered misconception ────────────
    graded = await _quiz_and_grade(
        path,
        KP[0],
        "种草就是想办法说服用户下单",
        expected="帮助用户发现并实现其向往的生活",
        misconception="种草就是说服用户购买",
    )
    assert graded["is_correct"] is False
    assert graded["misconception_recorded"] is True

    plan = await _plan(path)
    assert plan["decision"]["action"] == "remediate_misconception"
    assert plan["misconception"]["correction"].startswith("种草是帮助用户发现")

    # ── 4. qualitative gate: Feynman-style pass on kp0 ──────────────────
    assessed = await _assess(path, KP[0], True)
    assert assessed["mastered"] is True

    # ── 5. prerequisite order: kp1 before kp2/kp3 ───────────────────────
    plan = await _plan(path)
    assert plan["decision"]["action"] == "explain"
    assert plan["focus"]["node_id"] == KP[1]
    await _assess(path, KP[1], True)

    # ── 6. quantitative gate: three unaided correct answers ─────────────
    plan = await _plan(path)
    assert plan["focus"]["node_id"] == KP[2]
    for _ in range(3):
        graded = await _quiz_and_grade(
            path,
            KP[2],
            "产品确实解决问题、内容真实呈现体验、企业与用户利益基本一致",
            expected="产品确实解决问题；内容真实呈现体验；企业与用户利益基本一致",
            question_type="open",
        )
        assert graded["is_correct"] is True
    assert graded["mastered"] is True

    # ── 7. design gate on the last objective ────────────────────────────
    plan = await _plan(path)
    assert plan["focus"]["node_id"] == KP[3]
    await _assess(path, KP[3], True)

    # ── 8. due review outranks completion (retention is evidence) ───────
    store = LearningStore()
    progress = store.load(path)
    for task in progress.review_queue:
        task.due_at = time.time() - 1  # the scheduled reviews come due
    store.save(progress)

    plan = await _plan(path)
    assert plan["decision"]["action"] == "review"
    review_answers = {
        KP[0]: "帮助用户发现并实现其向往的生活",
        KP[1]: "帮助用户发现并实现其向往的生活",
        KP[2]: "产品确实解决问题、内容真实呈现体验、企业与用户利益基本一致",
        KP[3]: "帮助用户发现并实现其向往的生活",
    }
    focus_id = plan["focus"]["node_id"]
    reviewed = await _quiz_and_grade(
        path,
        focus_id,
        review_answers[focus_id],
        expected=review_answers[focus_id],
    )
    assert reviewed["is_correct"] is True

    # ── 9. every gate cleared → COMPLETE, state is real ─────────────────
    plan = await _plan(path)
    assert plan["decision"]["action"] == "complete"
    progress = store.load(path)
    assert len(progress.quiz_attempts) >= 5
    assert progress.qualitative_mastery == {
        KP[0]: True,
        KP[1]: True,
        KP[3]: True,
    }
    assert progress.mastery_levels[KP[2]] >= 0.9
    assert plan["map"]["complete"] is True
    # decisions stayed traceable throughout
    assert plan["decision"]["trace"]["policies_evaluated"]

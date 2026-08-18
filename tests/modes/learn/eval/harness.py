"""Deterministic loop driver over the production mastery tool surface.

The harness plays the role of both the agent (poses questions via
``mastery_quiz`` / ``mastery_assess`` and grades via ``mastery_grade``) and
the learner (answers via the simulators in :mod:`~.learners`), consulting the
Teaching Engine via ``teaching_plan`` every round. No LLM, no randomness — a
fixed (material, learner, scope) always yields the same record, which makes
the evaluation machine-readable and diff-able across runs.

The record collected per run maps 1:1 to the goal's Evaluation Outputs
(material / goal / knowledge units / teaching rounds / assessment history /
mastery trajectory / misconceptions / scaffold trajectory / final completion
state / decision traces / failures).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import time
from typing import Any

from deeptutor.tools.mastery_tool import (
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryGoalTool,
    MasteryGradeTool,
    MasteryQuizTool,
    TeachingPlanTool,
)
from lumen.modes.learn.adapters.storage import LearningStore

from .learners import Learner
from .materials import BenchmarkMaterial

__all__ = ["LoopRecord", "run_loop", "force_reviews_due", "kp_type_from_progress"]


@dataclass
class LoopRecord:
    """Machine-readable outcome of one (material x learner) run."""

    material: str
    learner: str
    goal: dict[str, Any] = field(default_factory=dict)
    knowledge_units: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    assessment_history: list[dict[str, Any]] = field(default_factory=list)
    mastery_trajectory: dict[str, list[float]] = field(default_factory=dict)
    misconceptions: list[dict[str, Any]] = field(default_factory=list)
    scaffold_trajectory: list[str] = field(default_factory=list)
    final_state: dict[str, Any] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "learner": self.learner,
            "goal": self.goal,
            "knowledge_units": self.knowledge_units,
            "rounds": self.rounds,
            "assessment_history": self.assessment_history,
            "mastery_trajectory": self.mastery_trajectory,
            "misconceptions": self.misconceptions,
            "scaffold_trajectory": self.scaffold_trajectory,
            "final_state": self.final_state,
            "failures": self.failures,
            "completed": self.completed,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def kp_type_from_progress(progress: Any, kp_id: str) -> str:
    """The knowledge type string for *kp_id* from the built progress."""
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return kp.type.value
    return ""


def owning_kp_id(focus_node_id: str) -> str:
    """Map a plan focus (kp id or misconception node id) to its kp id."""
    marker = "__mis"
    if marker in focus_node_id:
        return focus_node_id.split(marker, 1)[0]
    return focus_node_id


def kp_ids_for(path_id: str, material: BenchmarkMaterial) -> list[str]:
    """The actual generated kp ids for *path_id* (mirrors _parse_modules)."""
    return [
        f"{path_id}_m{m}_kp{j}"
        for m, mod in enumerate(material.modules)
        for j in range(len(mod.knowledge_points))
    ]


def _question_type_for(answer: str) -> str:
    return "open" if ("；" in answer or "、" in answer) else "short"


def force_reviews_due(progress: Any) -> None:
    """Make every scheduled review due now (used by retention scenarios)."""
    now = time.time()
    for task in progress.review_queue:
        task.due_at = now - 1


async def run_loop(
    material: BenchmarkMaterial,
    learner: Learner,
    *,
    path_id: str | None = None,
    scope: str = "all",  # "all" | "first_module"
    max_rounds: int = 400,
    store_root: Path | None = None,
    lesson: str = "",
) -> LoopRecord:
    """Run the deterministic teaching loop for one material x learner.

    Returns a :class:`LoopRecord`. ``store_root`` isolates persistence (the
    caller is responsible for pointing it at a temp dir in tests); when
    ``None`` the default workspace store is used.
    """
    path_id = path_id or f"eval_{material.id}_{learner.name}"
    store = LearningStore(root=store_root)
    record = LoopRecord(material=material.id, learner=learner.name)
    kp_ids = kp_ids_for(path_id, material)
    # kp id -> benchmark knowledge point (ids mirror _parse_modules generation)
    bench_by_id: dict[str, Any] = {}
    for m, module in enumerate(material.modules):
        for j, kp in enumerate(module.knowledge_points):
            bench_by_id[f"{path_id}_m{m}_kp{j}"] = replace(kp, id=f"{path_id}_m{m}_kp{j}")

    # ── build path + goal ────────────────────────────────────────────────
    build = json.loads(
        (
            await MasteryBuildTool().execute(
                _mastery_path_id=path_id, modules=material.as_build_payload(), mode="replace"
            )
        ).content
    )
    if build.get("status") != "built":
        record.failures.append({"phase": "build", "detail": build})
        return record

    if scope == "first_module":
        scope_kp_ids = kp_ids[: len(material.modules[0].knowledge_points)]
    else:
        scope_kp_ids = list(kp_ids)
    goal = json.loads(
        (
            await MasteryGoalTool().execute(
                _mastery_path_id=path_id,
                name=lesson or f"掌握《{material.title}》",
                scope_kp_ids=scope_kp_ids,
            )
        ).content
    )
    record.goal = {"name": goal["goal"]["name"], "scope": goal["goal"]["scope"]}

    progress = store.load(path_id)
    for module in progress.modules:
        for kp in module.knowledge_points:
            record.knowledge_units.append(
                {
                    "id": kp.id,
                    "name": kp.name,
                    "type": kp.type.value,
                    "source_ref": kp.source_ref,
                    "module": module.name,
                }
            )

    # ── teaching loop ────────────────────────────────────────────────────
    for round_no in range(1, max_rounds + 1):
        plan_payload = json.loads(
            (await TeachingPlanTool().execute(_mastery_path_id=path_id)).content
        )
        if plan_payload.get("status") != "active":
            record.failures.append({"phase": "plan", "round": round_no, "detail": plan_payload})
            break

        decision = plan_payload["decision"]
        action = decision["action"]
        focus = decision.get("target_node_id") or ""
        learner.on_plan(action, focus)
        record.scaffold_trajectory.append(decision.get("scaffold_level", "none"))

        round_meta = _round(round_no, decision, plan_payload)
        record.rounds.append(round_meta)

        if action == "complete":
            record.completed = True
            break

        progress = store.load(path_id)  # fresh state before acting
        outcome = await _act(
            record,
            progress=progress,
            store=store,
            path_id=path_id,
            plan_payload=plan_payload,
            learner=learner,
            bench_by_id=bench_by_id,
        )
        if outcome is None:
            record.failures.append({"phase": "act", "round": round_no, "action": action})
            break
        round_meta["graded"] = outcome.get("graded", False)
        round_meta["is_correct"] = outcome.get("is_correct")
        round_meta["mastery_after"] = outcome.get("mastery_after")
    else:
        # the loop exhausted max_rounds without COMPLETE — a real failure
        # signal (e.g. a learner stuck oscillating, or a stuck misconception)
        record.failures.append(
            {"phase": "max_rounds", "round": max_rounds, "last_action": record.rounds[-1]["action"] if record.rounds else ""}
        )

    # ── final state ──────────────────────────────────────────────────────
    progress = store.load(path_id)
    final_map = _map_summary(progress)
    record.final_state = {
        "complete": final_map.get("complete", False),
        "counts": final_map.get("counts", {}),
        "goal": final_map.get("goal", {}),
        "mastery": dict(progress.mastery_levels),
        "qualitative_mastery": dict(progress.qualitative_mastery),
        "attempts": {
            kp_id: len(
                [a for a in progress.quiz_attempts if a.knowledge_point_id == kp_id]
            )
            for kp_id in material.kp_ids()
        },
        "error_records": [
            {
                "kp": rec.knowledge_point_id,
                "status": rec.status,
                "misconception_node_id": rec.misconception_node_id,
                "retry_count": len(rec.retry_history),
            }
            for rec in progress.error_records
        ],
    }
    record.assessment_history = [
        {
            "kp": a.knowledge_point_id,
            "question_id": a.question_id,
            "correct": a.is_correct,
            "kind": getattr(a, "question_kind", "recall"),
            "misconception_node_id": a.misconception_node_id,
            "mastery": a.mastery_estimate,
        }
        for a in progress.quiz_attempts
    ]
    return record


def _round(round_no: int, decision: dict[str, Any], plan_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": round_no,
        "action": decision["action"],
        "focus": decision.get("target_node_id", ""),
        "strategy": decision.get("strategy", ""),
        "scaffold": decision.get("scaffold_level", ""),
        "reason": decision.get("reason", ""),
        "trace": decision.get("trace", {}),
        "instruction": plan_payload.get("instruction", {}),
        "misconception": plan_payload.get("misconception"),
        # source-grounding payload for the focused node (title/content/source_refs)
        "focus_payload": plan_payload.get("focus", {}),
        "resources": plan_payload.get("resources", []),
    }


async def _act(
    record: LoopRecord,
    *,
    progress: Any,
    store: LearningStore,
    path_id: str,
    plan_payload: dict[str, Any],
    learner: Learner,
    bench_by_id: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute one plan action and grade the learner's response.

    ``bench_by_id`` maps kp id -> the benchmark's knowledge point (which
    carries the canonical answer + registered misconceptions); the stored
    progress only contributes the built type / modules.
    """
    decision = plan_payload["decision"]
    action = decision["action"]
    focus = decision.get("target_node_id") or ""
    kp_id = owning_kp_id(focus)
    kp = _find_kp(progress, kp_id)
    bench_kp = bench_by_id.get(kp_id)
    if kp is None or bench_kp is None:
        return None
    kp_type = kp.type.value

    # misconception remediation: learner re-articulates the difference
    if action == "remediate_misconception":
        learner.on_remediation(kp_id)
        if kp_type in ("concept", "design"):
            passed = learner.qualitative(bench_kp)
            res = json.loads(
                (
                    await MasteryAssessTool().execute(
                        _mastery_path_id=path_id,
                        knowledge_point_id=kp_id,
                        passed=passed,
                        feedback="re-verification after remediation",
                    )
                ).content
            )
            return {"graded": True, "is_correct": passed, "mastery_after": res.get("mastery")}
        outcome = learner.quiz(bench_kp, question_kind="recall")
        return await _quiz_and_grade(
            record, path_id, store, bench_kp, kp_id, kp_type, outcome, focus, action
        )

    # pending resolution (safety net — the harness grades immediately)
    if action == "resolve_pending":
        pending = store.load(path_id).pending_question
        if pending is None:
            return {"graded": False}
        question_kind = getattr(pending, "question_kind", "recall")
        outcome = learner.quiz(bench_kp, question_kind=question_kind)
        return await _quiz_and_grade(
            record,
            path_id,
            store,
            bench_kp,
            kp_id,
            kp_type,
            outcome,
            focus,
            action,
            expected=pending.expected_answer,
            question_type=pending.question_type,
            question_kind=question_kind,
        )

    # qualitative targets are Feynman-checked via mastery_assess, unless the
    # learner's profile wants a graded probe (misconception detection)
    if kp_type in ("concept", "design") and not learner.prefer_quiz(bench_kp):
        passed = learner.qualitative(bench_kp)
        res = json.loads(
            (
                await MasteryAssessTool().execute(
                    _mastery_path_id=path_id,
                    knowledge_point_id=kp_id,
                    passed=passed,
                    feedback="learner explanation" if passed else "incomplete",
                )
            ).content
        )
        return {"graded": True, "is_correct": passed, "mastery_after": res.get("mastery")}

    # quantitative: pose a question and grade the learner's answer
    question_kind = "review" if action == "review" else "recall"
    outcome = learner.quiz(bench_kp, question_kind=question_kind)
    return await _quiz_and_grade(
        record,
        path_id,
        store,
        bench_kp,
        kp_id,
        kp_type,
        outcome,
        focus,
        action,
        question_kind=question_kind,
    )


async def _quiz_and_grade(
    record: LoopRecord,
    path_id: str,
    store: LearningStore,
    bench_kp: Any,
    kp_id: str,
    kp_type: str,
    outcome: Any,
    focus: str,
    action: str,
    *,
    expected: str | None = None,
    question_type: str | None = None,
    question_kind: str = "recall",
) -> dict[str, Any] | None:
    expected = expected or bench_kp.answer
    question_type = question_type or _question_type_for(expected)
    quiz = json.loads(
        (
            await MasteryQuizTool().execute(
                _mastery_path_id=path_id,
                knowledge_point_id=kp_id,
                question=f"关于 {bench_kp.name}：请回答",
                expected_answer=expected,
                question_type=question_type,
                question_kind=question_kind,
            )
        ).content
    )
    if quiz.get("status") != "registered":
        record.failures.append({"phase": "quiz", "kp": kp_id, "detail": quiz})
        return None
    graded = json.loads(
        (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                answer=outcome.answer,
                question_id=quiz["question_id"],
                misconception=outcome.misconception,
            )
        ).content
    )
    if graded.get("misconception_recorded"):
        record.misconceptions.append(
            {
                "round": len(record.rounds),
                "kp": kp_id,
                "statement": outcome.misconception,
                "action": action,
            }
        )
    return {
        "graded": True,
        "is_correct": graded.get("is_correct"),
        "mastery_after": graded.get("mastery"),
    }


def _find_kp(progress: Any, kp_id: str) -> Any | None:
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return kp
    return None


def _map_summary(progress: Any) -> dict[str, Any]:
    from lumen.modes.learn.policy.policy import map_summary

    return map_summary(progress)

"""Mastery Path tools — the seam between the chat-loop tutor and the pure
mastery engine (:mod:`lumen.modes.learn`).

Canonical home: ``lumen/modes/learn/chat_tools`` (migrated from
``deeptutor/capabilities/mastery/tools``).  The legacy path re-exports these
for existing importers and tests only.

These tools are auto-mounted only when a mastery path is active on the
turn (via the chat loop mastery capability). The chat agent loop IS the tutor;
these tools let it read the gate and record outcomes, while the pedagogy —
what to teach, how to question, when to explain — stays the model's job. The
arithmetic (mastery, gate, spaced repetition) stays in the engine.

The active path id is injected server-side by the pipeline as
``_mastery_path_id``; the model never supplies it. Each call constructs a
fresh store + service (matching the REST router) so concurrent turns can't
race on a shared object.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any
import uuid

from lumen.modes.learn.assessment.choices import (
    format_options,
    has_option_bodies,
    parse_options,
    recover_options_from_turn,
    resolve_answer,
    resolve_choice_submission,
)
from lumen.modes.learn.assessment.pending import public_pending_question

# ``learning.models`` and ``learning.policy`` only depend on pydantic — safe to
# import at module load. ``learning.service`` / ``storage`` / ``scheduler``
# reach the path service (and so the runtime + tool registry), so importing
# them here would close an import cycle through the built-in registry. They
# are imported lazily inside the call paths instead (same pattern as the other
# builtin tools).
from lumen.modes.learn.domain.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    Misconception,
    PendingQuestion,
)
from lumen.modes.learn.policy.policy import (
    QUALITATIVE_TYPES,
    display_mastery,
    find_knowledge_point,
    gate_threshold,
    is_mastered,
    map_summary,
    next_objective,
)
from lumen.runtime.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

if TYPE_CHECKING:
    from lumen.modes.learn.application.service import LearningService

# Tool names the pipeline mounts together when a mastery path is active. Kept
# here so the mount policy and the registration list can't disagree.
MASTERY_TOOL_NAMES: tuple[str, ...] = (
    "teaching_plan",
    "mastery_status",
    "mastery_quiz",
    "mastery_grade",
    "mastery_assess",
    "mastery_build",
    "mastery_goal",
)

_QUESTION_TYPES = ("choice", "short", "open")
# question_kind tags the *evidence* a question produces: rote recall, transfer
# to a new situation, application, or a spaced-repetition review (mirrors
# EvidenceType so the assessment trail distinguishes them).
_QUESTION_KINDS = ("recall", "transfer", "application", "review")
_ALLOWED_KP_TYPES = {t.value for t in KnowledgeType}
logger = logging.getLogger(__name__)


def _new_service() -> LearningService:
    from lumen.modes.learn.adapters.storage import LearningStore
    from lumen.modes.learn.application.service import LearningService

    return LearningService(LearningStore())


def _resolve_path_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_mastery_path_id") or "").strip()


def _resolve_session_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_session_id") or "").strip()


def _resolve_turn_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_turn_id") or "").strip()


def _question_bank_type(question_type: str) -> str:
    qtype = str(question_type or "").strip().lower()
    if qtype == "choice":
        return "choice"
    if qtype == "open":
        return "written"
    return "short_answer"


def _match_misconception(progress: LearningProgress, kp_id: str, statement: str) -> str:
    """Match a tutor-supplied misconception statement against the ones
    registered on *kp_id* and return the deterministic misconception node id
    (``{kp_id}__mis{i}``), or ``""`` when nothing matches.

    The model never supplies node ids — it describes the belief it observed;
    the server decides which registered misconception (if any) that is.
    """
    from difflib import SequenceMatcher

    text = " ".join(str(statement or "").strip().lower().split())
    if not text:
        return ""
    registered: list[tuple[str, str]] = []
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                registered = [
                    (" ".join(m.statement.lower().split()), m.statement) for m in kp.misconceptions
                ]
    if not registered:
        return ""
    best_index, best_score = -1, 0.0
    for i, (normalized, _original) in enumerate(registered):
        score = SequenceMatcher(None, text, normalized).ratio()
        if normalized in text or text in normalized:
            score = max(score, 0.9)
        if score > best_score:
            best_index, best_score = i, score
    if best_index < 0 or best_score < 0.55:
        return ""
    return f"{kp_id}__mis{best_index}"


def _node_payload(graph: Any, node_id: str) -> dict[str, Any]:
    """Grounding payload for a teaching node: title, content and source refs
    from the teaching graph (falls back to the bare id)."""
    if not node_id:
        return {"node_id": "", "title": ""}
    payload: dict[str, Any] = {"node_id": node_id, "title": node_id}
    try:
        if graph is not None and graph.has_node(node_id):
            node = graph.node(node_id)
            payload["title"] = node.title
            if node.content:
                payload["content"] = node.content
            if node.source_refs:
                payload["source_refs"] = list(node.source_refs)
            if node.type == "misconception" or getattr(node.type, "value", "") == "misconception":
                payload["type"] = "misconception"
                correction = node.metadata.get("correction", "")
                if correction:
                    payload["correction"] = correction
    except Exception:
        logger.warning("Failed to build node payload for %s", node_id, exc_info=True)
    return payload


def _normalize_quiz_contract(
    raw_question_type: Any,
    raw_options: Any,
    expected_answer: str,
) -> tuple[str, list[str], str]:
    """Validate and canonicalise the persisted quiz shape.

    A missing question type is inferred from the actual payload: options mean
    ``choice`` and no options mean ``short``. Once a caller explicitly chooses
    ``short`` or ``open``, options are rejected instead of being silently
    discarded. Choice answers are stored as labels so the interactive card and
    deterministic grader always compare the same representation.
    """
    if raw_options is None:
        options: list[str] = []
    elif not isinstance(raw_options, list):
        raise ValueError("mastery_quiz.options must be an array of non-empty strings.")
    elif any(not isinstance(option, str) or not option.strip() for option in raw_options):
        raise ValueError("mastery_quiz.options must contain only non-empty strings.")
    else:
        options = [option.strip() for option in raw_options]

    supplied_type = str(raw_question_type or "").strip().lower()
    if supplied_type and supplied_type not in _QUESTION_TYPES:
        allowed = ", ".join(_QUESTION_TYPES)
        raise ValueError(f"mastery_quiz.question_type must be one of: {allowed}.")

    question_type = supplied_type or ("choice" if options else "short")
    if question_type != "choice":
        if options:
            raise ValueError(
                f"mastery_quiz.options cannot be used with question_type={question_type!r}; "
                "omit options or use question_type='choice'."
            )
        return question_type, [], expected_answer

    choice_options = parse_options(options)
    if len(choice_options) != len(options):
        raise ValueError(
            "Choice option labels must be unique; retry mastery_quiz with one full body "
            "for each label."
        )
    if not has_option_bodies(choice_options):
        raise ValueError(
            "Choice questions need full option bodies in mastery_quiz.options "
            "(for example ['A: first answer', 'B: second answer']), not only "
            "the labels A/B/C/D. Retry mastery_quiz with the exact option "
            "descriptions you will show through ask_user."
        )

    resolved_expected = resolve_answer(expected_answer, choice_options)
    if not resolved_expected:
        raise ValueError(
            "Choice expected_answer must be an option label such as A/B/C/D, "
            "or uniquely match one full option body. Retry mastery_quiz with "
            "the correct label."
        )
    return question_type, format_options(choice_options), resolved_expected


async def _resolve_pending_choice(
    pending: PendingQuestion, turn_id: str
) -> tuple[dict[str, str], str]:
    """Resolve a pending choice question's ``({label: body}, expected_label)``.

    The persisted options are authoritative. For legacy paths that stored only
    ``["A", "B", ...]`` it recovers the real bodies from the turn's
    ``ask_user`` event. The expected answer is normalised to a stable label
    when it resolves, else left as registered.
    """
    options = parse_options(list(pending.options or []))
    if not has_option_bodies(options):
        try:
            from lumen.runtime.session import get_sqlite_session_store

            options = await recover_options_from_turn(
                get_sqlite_session_store(), turn_id, pending.prompt
            )
        except Exception:
            logger.warning("Failed to recover legacy mastery choice options", exc_info=True)
            options = {}
    return options, resolve_answer(pending.expected_answer, options) or pending.expected_answer


async def _sync_mastery_attempt_to_question_bank(
    *,
    session_id: str,
    turn_id: str,
    pending: PendingQuestion,
    user_answer: str,
    is_correct: bool,
    choice_options: dict[str, str] | None = None,
    correct_answer: str | None = None,
) -> None:
    if not session_id:
        return
    item = {
        "turn_id": turn_id,
        "question_id": pending.question_id,
        "question": pending.prompt,
        "question_type": _question_bank_type(pending.question_type),
        "options": choice_options or parse_options(list(pending.options or [])),
        "correct_answer": correct_answer or pending.expected_answer,
        "explanation": "",
        "difficulty": "",
        "user_answer": user_answer,
        "is_correct": is_correct,
    }
    try:
        from lumen.runtime.session import get_sqlite_session_store

        await get_sqlite_session_store().upsert_notebook_entries(session_id, [item])
    except Exception:
        logger.warning(
            "Failed to sync mastery question %s to question bank for session %s",
            pending.question_id,
            session_id,
            exc_info=True,
        )


def _json_result(payload: dict[str, Any], *, meta_key: str, success: bool = True) -> ToolResult:
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=success,
        metadata={meta_key: payload},
    )


def _no_path_result() -> ToolResult:
    return ToolResult(
        content="No mastery path is active on this turn; mastery tools are unavailable.",
        success=False,
    )


class TeachingPlanTool(BaseTool):
    """Consult the Teaching Engine for the deterministic next teaching action.

    The engine owns *what happens next*; the agent only executes the action via
    the other mastery tools. This is the deterministic decision seam described
    in the Teaching Core implementation report.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="teaching_plan",
            description=(
                "Consult the Teaching Engine for the deterministic next teaching "
                "action. It reads the learner's mastery path, the teaching "
                "knowledge graph, and the learner's current state and decides "
                "what to teach next: explain, show an example, scaffolded "
                "practice, assess, spaced review, remediate a misconception, "
                "resolve a pending question, or complete. Call this FIRST on "
                "every mastery turn — the engine owns the decision, never guess "
                "the next teaching action yourself. Then execute the returned "
                "instruction with the indicated mastery tool."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        service = _new_service()
        progress = service.get_or_create(path_id)
        if not any(module.knowledge_points for module in progress.modules):
            return _json_result(
                {
                    "status": "no_path",
                    "message": (
                        "No mastery path has been built yet. Design one from the "
                        "learner's materials and call mastery_build."
                    ),
                },
                meta_key="teaching_plan",
            )

        from lumen.modes.learn.adapters.learner_state import action_instruction
        from lumen.modes.learn.application.teaching_service import TeachingService

        teaching = TeachingService()
        action = teaching.decide(path_id)
        node_title = _node_title(teaching, progress, action.focus_node_id)
        instruction = action_instruction(action, node_title=node_title)
        try:
            graph = teaching.get_graph(progress.book_id)
        except Exception:
            logger.warning("Failed to load teaching graph for grounding", exc_info=True)
            graph = None
        focus_payload = _node_payload(graph, action.focus_node_id)
        resources = [_node_payload(graph, rid) for rid in action.resource_node_ids]
        misconception = None
        if focus_payload.get("type") == "misconception":
            misconception = {
                "statement": focus_payload.get("content", node_title),
                "correction": focus_payload.get("correction", ""),
            }
        return _json_result(
            {
                "status": "active",
                "decision": action.to_dict(),
                "instruction": instruction,
                "focus": focus_payload,
                "misconception": misconception,
                "resources": resources,
                "map": map_summary(progress),
            },
            meta_key="teaching_plan",
        )


def _node_title(
    teaching: Any,
    progress: LearningProgress,
    node_id: str,
) -> str:
    """Resolve a human title for a teaching node id (graph, then progress)."""
    if not node_id:
        return ""
    try:
        graph = teaching.get_graph(progress.book_id)
        if graph is not None and graph.has_node(node_id):
            return graph.node(node_id).title
    except Exception:
        logger.warning("Failed to resolve teaching node title for %s", node_id, exc_info=True)
    kp, _, _ = find_knowledge_point(progress, node_id)
    return kp.name if kp else node_id


class MasteryStatusTool(BaseTool):
    """Read the current objective + map snapshot. Call FIRST every turn."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_status",
            description=(
                "Read the learner's mastery path: the next objective to work on "
                "(decided by a hard mastery gate), any question awaiting an "
                "answer, due reviews, and a map of every objective's status "
                "(new / learning / mastered). Call this FIRST on every mastery "
                "turn — it tells you what to do; never guess the next objective."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        service = _new_service()
        progress = service.get_or_create(path_id)
        if not any(module.knowledge_points for module in progress.modules):
            return _json_result(
                {
                    "status": "empty",
                    "message": (
                        "No mastery path has been built yet. Design one from the "
                        "learner's materials and call mastery_build."
                    ),
                },
                meta_key="mastery_status",
            )
        payload = {
            "status": "active",
            "next": next_objective(progress).to_dict(),
            "map": map_summary(progress),
        }
        return _json_result(payload, meta_key="mastery_status")


class MasteryQuizTool(BaseTool):
    """Register an objective-type question; the engine holds the answer."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_quiz",
            description=(
                "Pose a question for a MEMORY or PROCEDURE objective and register "
                "its expected answer with the engine (so grading is deterministic "
                "and you never re-state the answer later). After calling this, "
                "present the question with the ask_user tool so the learner answers "
                "on an interactive card (for choices, give ask_user options short "
                "labels like A/B/C, pass every full option body here, and set the "
                "correct label as expected_answer); "
                "then call mastery_grade with their answer. For CONCEPT / DESIGN "
                "objectives use mastery_assess instead."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="question",
                    type="string",
                    description="The question text shown to the learner.",
                ),
                ToolParameter(
                    name="expected_answer",
                    type="string",
                    description="The correct answer, used only server-side for grading.",
                ),
                ToolParameter(
                    name="question_type",
                    type="string",
                    description=(
                        "'choice' (exact match), 'short' (exact / fuzzy for ≤30 "
                        "chars), or 'open' (keyword overlap). When omitted, options "
                        "infer 'choice'; otherwise the default is 'short'."
                    ),
                    required=False,
                    default="short",
                    enum=list(_QUESTION_TYPES),
                ),
                ToolParameter(
                    name="question_kind",
                    type="string",
                    description=(
                        "What the question tests: 'recall' (rote / verbatim), "
                        "'transfer' (apply the idea to a new situation), "
                        "'application', or 'review' (a spaced-repetition check). "
                        "Default 'recall'. The kind is recorded as evidence so "
                        "mastery is never judged on rote recall alone."
                    ),
                    required=False,
                    default="recall",
                    enum=list(_QUESTION_KINDS),
                ),
                ToolParameter(
                    name="options",
                    type="array",
                    description=(
                        "Every full choice option in label order; providing options "
                        "infers question_type='choice' when the type is omitted. "
                        "for example ['A: first answer', 'B: second answer']. Never "
                        "pass options for 'short'/'open' or bare labels such as "
                        "['A', 'B', 'C', 'D']. Use the same bodies as the ask_user "
                        "option descriptions."
                    ),
                    required=False,
                    items={"type": "string"},
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        question = str(kwargs.get("question") or "").strip()
        expected = str(kwargs.get("expected_answer") or "").strip()
        if not kp_id or not question or not expected:
            return ToolResult(
                content="mastery_quiz needs knowledge_point_id, question, and expected_answer.",
                success=False,
            )
        try:
            q_type, options, expected = _normalize_quiz_contract(
                kwargs.get("question_type"), kwargs.get("options"), expected
            )
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)
        question_kind = str(kwargs.get("question_kind") or "recall").strip().lower()
        if question_kind not in _QUESTION_KINDS:
            allowed = ", ".join(_QUESTION_KINDS)
            return ToolResult(
                content=f"mastery_quiz.question_kind must be one of: {allowed}.",
                success=False,
            )

        service = _new_service()
        progress = service.get_or_create(path_id)
        kp, module_id, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            return ToolResult(
                content=f"Unknown objective {kp_id!r}; call mastery_status for valid ids.",
                success=False,
            )
        pending = PendingQuestion(
            question_id=uuid.uuid4().hex,
            knowledge_point_id=kp_id,
            module_id=module_id,
            prompt=question,
            question_type=q_type,
            question_kind=question_kind,
            expected_answer=expected,
            options=options,
        )
        service.set_pending_question(progress, pending)
        public_question = public_pending_question(pending)
        return _json_result(
            {
                "status": "registered",
                "knowledge_point_id": kp_id,
                "question_id": pending.question_id,
                "question_type": pending.question_type,
                "question": question,
                "options": options,
                "pending_question": public_question.to_dict(),
                "ask_user": {"questions": [public_question.to_ask_user_dict()]},
                "instruction": (
                    "Pass ask_user.questions through unchanged: its question id and "
                    "option labels are bound to the persisted question. Then call "
                    "mastery_grade with the learner's answer and this question_id."
                ),
            },
            meta_key="mastery_quiz",
        )


class MasteryGradeTool(BaseTool):
    """Grade the learner's answer to the pending question (deterministic)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_grade",
            description=(
                "Grade the learner's answer to the question you registered with "
                "mastery_quiz. Grading is deterministic against the stored "
                "expected answer; this updates mastery, advances spaced "
                "repetition, and tells you whether the objective's gate is now "
                "cleared. Then give the learner feedback."
            ),
            parameters=[
                ToolParameter(
                    name="answer",
                    type="string",
                    description="The learner's answer, verbatim.",
                ),
                ToolParameter(
                    name="question_id",
                    type="string",
                    description=(
                        "Stable question_id from mastery_quiz or mastery_status. "
                        "Optional only for legacy pending questions."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="misconception",
                    type="string",
                    description=(
                        "When the answer is wrong AND matches a misconception "
                        "registered on this objective (see mastery_build), pass "
                        "that misconception's statement here; the engine records "
                        "it and remediates it before any new teaching. Optional."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

        answer = str(kwargs.get("answer") or "")
        service = _new_service()
        scheduler = SpacedRepetitionScheduler()
        progress = service.get_or_create(path_id)
        pending = progress.pending_question
        if pending is None:
            return ToolResult(
                content="No question is awaiting an answer. Pose one with mastery_quiz first.",
                success=False,
            )
        submitted_question_id = str(kwargs.get("question_id") or "").strip()
        if submitted_question_id and submitted_question_id != pending.question_id:
            return ToolResult(
                content=(
                    f"Question {submitted_question_id!r} is no longer pending; "
                    f"call mastery_status and answer {pending.question_id!r}."
                ),
                success=False,
            )
        choice_options: dict[str, str] = {}
        expected_answer = pending.expected_answer
        answer_for_grading = answer
        if pending.question_type == "choice":
            choice_options, expected_answer = await _resolve_pending_choice(
                pending, _resolve_turn_id(kwargs)
            )
            answer_for_grading = resolve_choice_submission(answer, choice_options) or answer

        # Server-side misconception match: the tutor describes the belief it
        # observed; only registered misconceptions can ever be recorded.
        misconception_node_id = _match_misconception(
            progress, pending.knowledge_point_id, str(kwargs.get("misconception") or "")
        )

        is_correct = service.grade_and_record(
            progress,
            question_id=pending.question_id,
            knowledge_point_id=pending.knowledge_point_id,
            module_id=pending.module_id,
            user_answer=answer_for_grading,
            expected_answer=expected_answer,
            question_type=pending.question_type,
            scheduler=scheduler,
            misconception_node_id=misconception_node_id,
            question_kind=pending.question_kind,
        )
        await _sync_mastery_attempt_to_question_bank(
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
            pending=pending,
            user_answer=answer,
            is_correct=is_correct,
            choice_options=choice_options,
            correct_answer=expected_answer,
        )
        service.clear_pending_question(progress)
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
        mastered = bool(kp and is_mastered(progress, kp))
        payload = {
            "is_correct": is_correct,
            "knowledge_point_id": pending.knowledge_point_id,
            "mastery": round(display_mastery(progress, kp), 3) if kp else 0.0,
            "threshold": round(gate_threshold(kp.type), 3) if kp else 0.0,
            "mastered": mastered,
            "misconception_recorded": bool(misconception_node_id and not is_correct),
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_grade")


class MasteryAssessTool(BaseTool):
    """Record the qualitative (CONCEPT / DESIGN) gate from a Feynman check."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_assess",
            description=(
                "Record your judgement of a CONCEPT or DESIGN objective after the "
                "learner explains it in their own words (a Feynman-style check). "
                "Pass passed=true only when the explanation is correct and "
                "complete enough to count as mastery — this is the gate for these "
                "objective types. For MEMORY / PROCEDURE objectives use "
                "mastery_quiz + mastery_grade instead."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="passed",
                    type="boolean",
                    description="True if the explanation demonstrates mastery.",
                ),
                ToolParameter(
                    name="feedback",
                    type="string",
                    description="Short note on what was strong or missing (stored as evidence).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        if not kp_id:
            return ToolResult(content="mastery_assess needs a knowledge_point_id.", success=False)
        passed = bool(kwargs.get("passed"))
        feedback = str(kwargs.get("feedback") or "").strip()

        service = _new_service()
        progress = service.get_or_create(path_id)
        kp, _, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            return ToolResult(
                content=f"Unknown objective {kp_id!r}; call mastery_status for valid ids.",
                success=False,
            )
        if kp.type not in QUALITATIVE_TYPES:
            return ToolResult(
                content=(
                    f"Objective {kp.name!r} is a {kp.type.value} type — gate it with "
                    "mastery_quiz + mastery_grade, not mastery_assess."
                ),
                success=False,
            )
        from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

        service.record_qualitative(
            progress,
            kp_id,
            passed=passed,
            evidence=feedback,
            scheduler=SpacedRepetitionScheduler(),
        )
        payload = {
            "knowledge_point_id": kp_id,
            "passed": passed,
            "mastered": is_mastered(progress, kp),
            "mastery": round(display_mastery(progress, kp), 3),
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_assess")


class MasteryBuildTool(BaseTool):
    """Create / extend the skill map from objectives the tutor designed."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_build",
            description=(
                "Create or extend the learner's mastery path. Design modules and "
                "their knowledge points from the learner's materials (use rag / "
                "read_source first when materials are attached) and pass them "
                "here. Each knowledge point needs a 'type': memory (facts), "
                "procedure (step-by-step skills), concept (ideas to understand), "
                "or design (open-ended judgement). Optionally ground each point "
                "with a short 'description' and a 'source_ref' locator into the "
                "material, and register the 'misconceptions' learners commonly "
                "hold about it ({statement, correction}) so wrong answers can be "
                "diagnosed and remediated. Use mode='replace' to start fresh or "
                "'append' to add to an existing path."
            ),
            parameters=[
                ToolParameter(
                    name="modules",
                    type="array",
                    description=(
                        "Ordered modules: each {name, knowledge_points: [{name, "
                        "type, description?, source_ref?, misconceptions?: "
                        "[{statement, correction}]}]}. type is one of "
                        "memory/procedure/concept/design."
                    ),
                    items={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "knowledge_points": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": sorted(_ALLOWED_KP_TYPES),
                                        },
                                        "description": {"type": "string"},
                                        "source_ref": {"type": "string"},
                                        "misconceptions": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "statement": {"type": "string"},
                                                    "correction": {"type": "string"},
                                                },
                                                "required": ["statement"],
                                            },
                                        },
                                    },
                                    "required": ["name"],
                                },
                            },
                        },
                        "required": ["name", "knowledge_points"],
                    },
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'replace' (default) starts fresh; 'append' adds modules.",
                    required=False,
                    default="replace",
                    enum=["replace", "append"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        mode = str(kwargs.get("mode") or "replace").strip().lower()
        if mode not in {"replace", "append"}:
            mode = "replace"

        service = _new_service()
        progress = service.get_or_create(path_id)
        offset = len(progress.modules) if mode == "append" else 0
        new_modules, error = _parse_modules(kwargs.get("modules"), path_id, offset)
        if error:
            return ToolResult(content=error, success=False)

        combined = (list(progress.modules) + new_modules) if mode == "append" else new_modules
        service.replace_modules(progress, combined)
        progress.pending_question = None  # a rebuilt map invalidates any open question
        if combined:
            progress.current_module_id = combined[0].id
            progress.current_kp_index = 0
        service.save(progress)
        self._rebuild_teaching_graph(path_id)
        kp_count = sum(len(m.knowledge_points) for m in new_modules)
        return _json_result(
            {
                "status": "built",
                "mode": mode,
                "modules_added": len(new_modules),
                "knowledge_points_added": kp_count,
                "map": map_summary(progress),
            },
            meta_key="mastery_build",
        )

    @staticmethod
    def _rebuild_teaching_graph(path_id: str) -> None:
        """Rebuild the persisted teaching graph so teaching_plan decisions
        always reflect the current module tree (a stale graph would keep
        deciding against removed / renamed objectives)."""
        try:
            from lumen.modes.learn.application.teaching_service import TeachingService

            TeachingService().rebuild_graph(path_id)
        except Exception:
            logger.warning("Failed to rebuild teaching graph for %s", path_id, exc_info=True)


def _parse_modules(
    raw_modules: Any, path_id: str, offset: int
) -> tuple[list[LearningModule], str | None]:
    """Validate the model-designed module tree into engine models.

    Ids are generated server-side (``<path>_m<i>_kp<j>``) so the model never
    controls storage keys; unknown knowledge types fall back to 'concept'.
    Optional grounding (description / source_ref) and registered
    misconceptions ride along onto the knowledge points.
    """
    if not isinstance(raw_modules, list) or not raw_modules:
        return [], "mastery_build needs a non-empty 'modules' array."
    modules: list[LearningModule] = []
    for i, raw in enumerate(raw_modules):
        if not isinstance(raw, dict):
            continue
        index = offset + i
        name = str(raw.get("name") or "").strip()[:200]
        if not name:
            continue
        module_id = f"{path_id}_m{index}"
        kps: list[KnowledgePoint] = []
        for j, raw_kp in enumerate(raw.get("knowledge_points") or []):
            if not isinstance(raw_kp, dict):
                continue
            kp_name = str(raw_kp.get("name") or "").strip()[:200]
            if len(kp_name) < 2:
                continue
            kp_type = str(raw_kp.get("type") or "concept").strip().lower()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
            misconceptions: list[Misconception] = []
            for raw_mis in raw_kp.get("misconceptions") or []:
                if not isinstance(raw_mis, dict):
                    continue
                statement = str(raw_mis.get("statement") or "").strip()[:500]
                if len(statement) < 3:
                    continue
                misconceptions.append(
                    Misconception(
                        statement=statement,
                        correction=str(raw_mis.get("correction") or "").strip()[:1000],
                    )
                )
            kps.append(
                KnowledgePoint(
                    id=f"{module_id}_kp{j}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=module_id,
                    description=str(raw_kp.get("description") or "").strip()[:1000],
                    source_ref=str(raw_kp.get("source_ref") or "").strip()[:200],
                    misconceptions=misconceptions,
                )
            )
        if not kps:
            continue
        modules.append(LearningModule(id=module_id, name=name, order=index, knowledge_points=kps))
    if not modules:
        return [], "No valid modules: each module needs a name and at least one knowledge point."
    return modules, None


class MasteryGoalTool(BaseTool):
    """Set / inspect the learner's explicit learning goal (scope + name)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_goal",
            description=(
                "Set or inspect the learner's explicit learning goal: which "
                "objectives count toward completion and what the learner is "
                "aiming for. Call this when the learner states an intent like "
                "'I only need chapter 3 for the exam' or 'I want to finish "
                "everything'. Without a scope every objective gates completion."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="The learner-facing goal intent (e.g. 'pass the midterm').",
                    required=False,
                ),
                ToolParameter(
                    name="scope_kp_ids",
                    type="array",
                    description=(
                        "Objective ids (verbatim from mastery_status) that gate "
                        "completion. Omit or pass [] to target the whole path. "
                        "Prerequisites of scoped objectives still gate teaching "
                        "order."
                    ),
                    required=False,
                    items={"type": "string"},
                ),
                ToolParameter(
                    name="clear",
                    type="boolean",
                    description="Reset the goal to the whole path (ignores name/scope).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        service = _new_service()
        progress = service.get_or_create(path_id)
        known = {kp.id for module in progress.modules for kp in module.knowledge_points}

        if bool(kwargs.get("clear")):
            progress.goal_name = ""
            progress.goal_kp_ids = []
        else:
            name = str(kwargs.get("name") or "").strip()[:200]
            if name:
                progress.goal_name = name
            raw_scope = kwargs.get("scope_kp_ids")
            if raw_scope is not None:
                if not isinstance(raw_scope, list) or any(
                    not isinstance(item, str) for item in raw_scope
                ):
                    return ToolResult(
                        content="mastery_goal.scope_kp_ids must be an array of objective ids.",
                        success=False,
                    )
                scope = [kp_id.strip() for kp_id in raw_scope if kp_id.strip() in known]
                dropped = len(raw_scope) - len(scope)
                progress.goal_kp_ids = scope
                if dropped:
                    logger.warning(
                        "mastery_goal dropped %d unknown objective ids for %s", dropped, path_id
                    )
        progress.updated_at = time.time()
        service.save(progress)

        scope = progress.goal_kp_ids
        payload = {
            "status": "set" if not kwargs.get("clear") else "cleared",
            "goal": {
                "name": progress.goal_name,
                "scope_kp_ids": list(scope),
                "scope": "all" if not scope else "subset",
            },
            "map": map_summary(progress),
        }
        return _json_result(payload, meta_key="mastery_goal")


MASTERY_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    TeachingPlanTool,
    MasteryStatusTool,
    MasteryQuizTool,
    MasteryGradeTool,
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryGoalTool,
)


__all__ = [
    "MASTERY_TOOL_NAMES",
    "MASTERY_TOOL_TYPES",
    "TeachingPlanTool",
    "MasteryStatusTool",
    "MasteryQuizTool",
    "MasteryGradeTool",
    "MasteryAssessTool",
    "MasteryBuildTool",
    "MasteryGoalTool",
]

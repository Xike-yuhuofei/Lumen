"""Teaching Session Graph — the Minimal teaching-loop orchestrator.

The graph owns the pedagogical control flow.  It walks the closed loop

    SNAPSHOT -> ASSESS -> DIAGNOSE -> DECIDE -> ACT -> COMMIT -> CONTINUE / TERMINATE

once per Agent Runtime execution, using:

* the deterministic Teaching Engine for every ``PolicyDecision`` (never the LLM);
* the Agent Runtime ONLY as the content / interaction primitive (its
  ``run`` is called to generate learner-facing content, and its
  interrupt/resume seam is reused to collect answers) — nothing here
  re-implements the loop, streaming, tools, budget, or checkpoint;
* :class:`TeachingGraphDomain` for every authoritative Learner-Domain write,
  so no effect bypasses the Domain Commit Foundation;
* the durable Teaching Session ↔ execution lifecycle (governor) + graph-node
  checkpoint for crash / restart recovery.

Multi-turn continuity is safe because each run re-reads a *fresh* snapshot and
every commit is idempotent (a crash before / after commit collapses to one
effect).  No stale state is ever silently advanced.
"""

from __future__ import annotations

import logging
from typing import Any

from lumen.modes.learn.adapters.storage import LearningStore
from lumen.modes.learn.application.teaching_service import TeachingService
from lumen.modes.learn.assessment.grading import grade_answer
from lumen.modes.learn.graph.checkpoint import TeachingGraphCheckpoint
from lumen.modes.learn.graph.contract import (
    GRAPH_TOPOLOGY,
    Lineage,
    PolicyDecision,
    TeachingNode,
    TeachRunOutcome,
)
from lumen.modes.learn.graph.domain_service import TeachingGraphDomain
from lumen.modes.learn.policy.policy import QUALITATIVE_TYPES
from lumen.modes.learn.policy.scheduler import SpacedRepetitionScheduler

logger = logging.getLogger(__name__)

# Content-generation actions: the graph delegates to the Agent Runtime to render
# them (streaming, usage, budget all stay on the runtime).  The LLM fills content
# *within* the decided action; it never decides the flow.
_CONTENT_ACTIONS = {
    "explain",
    "show_example",
    "review_prerequisite",
    "remediate_misconception",
}
# Assessment actions: the graph poses / grades and commits evidence itself.
_QUEST_ACTIONS = {"resolve_pending", "assess", "practice", "review"}


class TeachingSessionGraph:
    """Per-execution walker of the minimal teaching closed loop."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        domain: TeachingGraphDomain | None = None,
        teaching_service: TeachingService | None = None,
        checkpoint: TeachingGraphCheckpoint | None = None,
        scheduler: Any | None = None,
    ) -> None:
        self._store = store or LearningStore()
        self._domain = domain or TeachingGraphDomain(self._store)
        self._teaching = teaching_service or TeachingService(learning_store=self._store)
        self._checkpoint = checkpoint
        self._scheduler = scheduler or SpacedRepetitionScheduler()

    # ── public entry ────────────────────────────────────────────────────

    async def run_turn(
        self,
        *,
        path_id: str,
        teaching_session_id: str,
        execution_generation: str,
        execution_operation: str,
        resume_input: str | None,
        context: Any,
        stream: Any,
        agent_loop: Any,
        deps: dict[str, Any],
    ) -> TeachRunOutcome:
        """Walk the loop once for one Agent Runtime execution.

        Returns an audit-able :class:`TeachRunOutcome`.  All authoritative
        learner writes go through :class:`TeachingGraphDomain`.
        """
        # SNAPSHOT
        progress, version = self._domain.snapshot(path_id)
        self._record(teaching_session_id, execution_generation, TeachingNode.SNAPSHOT, version)
        if progress is None or not progress.modules:
            outcome = TeachRunOutcome(
                node=TeachingNode.TERMINATE,
                decision=PolicyDecision(decision_id=""),
                lineage=self._lineage(teaching_session_id, execution_generation),
                is_terminal=True,
                feedback="No learning path exists for this path_id.",
            )
            self._record(
                teaching_session_id, execution_generation, TeachingNode.TERMINATE, version
            )
            return outcome

        graph = self._teaching.get_graph(path_id)

        # ASSESS + DIAGNOSE: grade an incoming answer under its pose decision.
        self._record(teaching_session_id, execution_generation, TeachingNode.ASSESS, version)
        pending = progress.pending_question
        incoming_answer = self._incoming_answer(context, resume_input)
        graded = False
        if pending is not None and self._is_answerable(pending) and incoming_answer:
            graded = self._grade(progress, pending, incoming_answer, context)
            progress, version = self._domain.snapshot(path_id)
        self._record(teaching_session_id, execution_generation, TeachingNode.DIAGNOSE, version)

        # DECIDE: explicit PolicyDecision from the deterministic engine.
        decision = self._decide(path_id, progress)
        self._record(
            teaching_session_id,
            execution_generation,
            TeachingNode.DECIDE,
            version,
            decision_id=decision.decision_id,
        )
        lineage = self._lineage(
            teaching_session_id,
            execution_generation,
            decision_id=decision.decision_id,
        )

        if decision.action == "complete":
            self._record(teaching_session_id, execution_generation, TeachingNode.TERMINATE, version)
            return TeachRunOutcome(
                node=TeachingNode.TERMINATE,
                decision=decision,
                lineage=lineage,
                is_terminal=True,
                graded=graded,
                feedback="All learning-goal targets are mastered.",
            )

        # ACT
        self._record(teaching_session_id, execution_generation, TeachingNode.ACT, version)
        if decision.action in _CONTENT_ACTIONS:
            rendered = await self._delegate_content(agent_loop, context, stream, deps, decision)
            # A content pass (first exposure, scaffold, remediation) must leave
            # an assessable follow-up so evidence is produced and the loop can
            # advance — otherwise a fresh learner spins on `first_exposure`
            # forever (no Evidence ever emitted). The check is posed here and
            # graded (with full lineage) on the next execution. Only posed when
            # the content actually rendered, so a crashed runtime writes nothing.
            posed = False
            if rendered and progress.pending_question is None:
                question = self._build_question(decision, progress, graph)
                if question is not None:
                    self._domain.commit_pose(
                        progress,
                        question,
                        decision_payload=decision.to_payload(),
                        decision_id=decision.decision_id,
                    )
                    progress, version = self._domain.snapshot(path_id)
                    posed = True
            self._record(
                teaching_session_id, execution_generation, TeachingNode.CONTINUE, version
            )
            return TeachRunOutcome(
                node=TeachingNode.CONTINUE,
                decision=decision,
                lineage=lineage,
                posed_pending=posed,
            )

        if decision.action in _QUEST_ACTIONS:
            posed = False
            # POSE a fresh question when none is already set for this decision.
            if pending is None or graded:
                question = self._build_question(decision, progress, graph)
                if question is not None:
                    self._domain.commit_pose(
                        progress,
                        question,
                        decision_payload=decision.to_payload(),
                        decision_id=decision.decision_id,
                    )
                    progress, version = self._domain.snapshot(path_id)
                    posed = True
                else:
                    # Nothing sensible to assess; park as a continuation.
                    self._record(
                        teaching_session_id, execution_generation, TeachingNode.CONTINUE, version
                    )
                    return TeachRunOutcome(
                        node=TeachingNode.CONTINUE, decision=decision, lineage=lineage
                    )
            else:
                posed = True

            # Present the open question and, when the runtime offers a reply
            # waiter, collect + grade the answer in this same execution.
            answer = await self._interact(stream, context, progress.pending_question)
            if pending_after := progress.pending_question:
                if self._is_answerable(pending_after) and answer:
                    self._grade(progress, pending_after, answer, context)
                    graded = True
                    progress, version = self._domain.snapshot(path_id)
                    self._record(
                        teaching_session_id, execution_generation, TeachingNode.COMMIT, version
                    )
            self._record(
                teaching_session_id, execution_generation, TeachingNode.CONTINUE, version
            )
            return TeachRunOutcome(
                node=TeachingNode.CONTINUE,
                decision=decision,
                lineage=lineage,
                posed_pending=posed,
                graded=graded,
                committed=graded,
            )

        # Unknown action type — swallow defensively, keep the turn from failing.
        self._record(teaching_session_id, execution_generation, TeachingNode.CONTINUE, version)
        return TeachRunOutcome(
            node=TeachingNode.CONTINUE,
            decision=decision,
            lineage=lineage,
            feedback=f"Unhandled teaching action {decision.action!r}.",
        )

    # ── helpers ─────────────────────────────────────────────────────────

    def _lineage(
        self,
        teaching_session_id: str,
        execution_generation: str,
        *,
        decision_id: str = "",
    ) -> Lineage:
        return Lineage(
            teaching_session_id=teaching_session_id,
            execution_generation=execution_generation,
            decision_id=decision_id,
        )

    def _record(
        self,
        teaching_session_id: str,
        execution_generation: str,
        node: TeachingNode,
        version: int = 0,
        *,
        decision_id: str = "",
    ) -> None:
        if self._checkpoint is None:
            return
        self._checkpoint.record(
            teaching_session_id=teaching_session_id,
            execution_generation=execution_generation,
            last_node=node.value,
            learner_version=version,
            decision_id=decision_id,
        )

    def _decide(self, path_id: str, progress) -> PolicyDecision:
        action = self._teaching.decide(path_id)
        trace = getattr(action, "trace", None)
        trace_dict = trace.model_dump() if trace is not None else {}
        from lumen.modes.learn.graph.contract import CANDIDATE_POLICY_VERSION

        return PolicyDecision(
            decision_id=f"dec-{_hex(16)}",
            policy_version=CANDIDATE_POLICY_VERSION,
            action=str(getattr(action.action, "value", action.action)),
            focus_node_id=getattr(action, "focus_node_id", "") or "",
            strategy=str(getattr(action.strategy, "value", "")),
            reason=getattr(action, "reason", "") or "",
            policy_applied=str(trace_dict.get("policy_applied", "") or ""),
            trace=trace_dict,
        )

    def replay_decision(self, decision_id: str) -> PolicyDecision | None:
        """Decision Replay — reuse a previously committed immutable decision
        without re-running the Teaching Engine.

        Reads straight off the authoritative ``policy_decisions`` ledger and is
        strictly read-only: no learner effect, no checkpoint write, no policy
        invocation.  Returns ``None`` when the decision was never committed.
        """
        payload = self._domain.read_decision_payload(decision_id)
        if payload is None:
            return None
        return PolicyDecision(
            decision_id=decision_id,
            policy_version=str(payload.get("policy_version", "") or ""),
            action=str(payload.get("action", "") or ""),
            focus_node_id=str(payload.get("focus_node_id", "") or ""),
            strategy=str(payload.get("strategy", "") or ""),
            reason=str(payload.get("reason", "") or ""),
            policy_applied=str(payload.get("policy_applied", "") or ""),
            trace=payload.get("trace") or {},
        )

    def _incoming_answer(self, context: Any, resume_input: str | None) -> str:
        if resume_input not in (None, ""):
            return str(resume_input).strip()
        hint = (getattr(context, "metadata", {}) or {}).get("resume_input")
        if hint:
            return str(hint).strip()
        history = getattr(context, "conversation_history", None) or []
        if history:
            last = history[-1]
            if isinstance(last, dict) and last.get("role") == "user":
                return str(last.get("content") or "").strip()
        return ""

    @staticmethod
    def _is_answerable(pending) -> bool:
        return bool(getattr(pending, "decision_id", "") and getattr(pending, "expected_answer", ""))

    def _grade(self, progress, pending, answer: str, context: Any) -> bool:
        from lumen.modes.learn.assessment.choices import (
            parse_options,
            resolve_choice_submission,
        )

        choice_options: dict[str, str] = {}
        answer_for_grading = answer
        expected = pending.expected_answer
        if pending.question_type == "choice":
            choice_options = parse_options(list(pending.options or []))
            answer_for_grading = resolve_choice_submission(answer, choice_options) or answer

        is_correct = bool(expected) and grade_answer(
            answer_for_grading, expected, pending.question_type
        )
        kp_id = pending.knowledge_point_id or ""
        kp_type = progress.knowledge_types.get(kp_id)
        # CONCEPT / DESIGN objectives are gated qualitatively (their gate is set
        # by feynman evidence); a graded failure also matches any registered
        # misconception so the engine's remediation path becomes reachable.
        is_qual = kp_type in QUALITATIVE_TYPES or pending.question_kind == "application"
        matched = ""
        if not is_correct:
            matched = self._domain.match_misconception(progress, kp_id, answer)

        session_id = str(getattr(context, "session_id", "") or "")
        turn_id = str((getattr(context, "metadata", {}) or {}).get("turn_id") or "")
        decision_id = str(getattr(pending, "decision_id", "") or "")
        pose_payload = getattr(pending, "decision_payload", None) or None

        if is_qual:
            self._domain.commit_qualitative(
                progress,
                kp_id=kp_id,
                passed=is_correct,
                evidence_text=answer,
                scheduler=self._scheduler,
                misconception_node_id=matched,
                decision_id=decision_id,
                decision_payload=pose_payload,
                session_id=session_id,
                turn_id=turn_id,
            )
        else:
            self._domain.commit_grade(
                progress,
                pending=pending,
                user_answer=answer,
                choice_options=choice_options,
                expected_answer=expected,
                answer_for_grading=answer_for_grading,
                misconception_node_id=matched,
                scheduler=self._scheduler,
                session_id=session_id,
                turn_id=turn_id,
            )
        return is_correct

    @staticmethod
    def _owning_kp(focus: str) -> str:
        """Normalise a teaching-node id to its owning knowledge point.

        The engine's remediation policy targets a MISCONCEPTION node id
        (``{kp_id}__mis{i}``); an assessment must target the owning kp so it is
        graded against the right content and knowledge type.
        """
        marker = "__mis"
        return focus.split(marker, 1)[0] if marker in focus else focus

    def _build_question(self, decision: PolicyDecision, progress, graph) -> Any:
        """Pose a deterministic question for an assessment action.

        A real deployment would generate richer stems via the Agent Runtime; a
        minimal candidate needs a deterministic, gradeable question, so the stem
        is built from the focus node's own title/content and the expected answer
        from the same content (fail-closed gradeable, no LLM round-trip).

        Qualitative (CONCEPT / DESIGN) objectives are posed as a "application"
        (Feynman-style) check so their evidence drives the qualitative gate via
        :meth:`TeachingGraphDomain.commit_qualitative`.
        """
        from lumen.modes.learn.domain.models import PendingQuestion

        focus = decision.focus_node_id
        if not focus:
            return None
        kp_id = self._owning_kp(focus)
        if not kp_id:
            return None
        kp_type = progress.knowledge_types.get(kp_id)
        question_kind = (
            "application"
            if kp_type in QUALITATIVE_TYPES
            else (str(decision.trace.get("expected_evidence", "") or "") or "recall")
        )
        title, content = self._node_text(graph, progress, kp_id)
        if not content:
            content = title or kp_id
        words = [w for w in content.replace("\n", " ").split() if w]
        expected = " ".join(words[:24]) if words else ""
        if not expected:
            return None
        module_id = ""
        for mod in progress.modules:
            for kp in mod.knowledge_points:
                if kp.id == kp_id:
                    module_id = mod.id
                    break
        return PendingQuestion(
            question_id=f"gq-{_hex(8)}",
            knowledge_point_id=kp_id,
            module_id=module_id,
            prompt=(
                f"{title} — restate the key idea so we can check your "
                "understanding (based on the material you just worked through)."
            ),
            question_type="open",
            question_kind=question_kind,
            expected_answer=expected,
            options=[],
            decision_id=decision.decision_id,
            action_id=f"{decision.decision_id}:pose",
        )

    @staticmethod
    def _node_text(graph, progress, focus: str) -> tuple[str, str]:
        if graph is not None and graph.has_node(focus):
            node = graph.node(focus)
            return (getattr(node, "title", "") or focus, getattr(node, "content", "") or "")
        for mod in progress.modules:
            for kp in mod.knowledge_points:
                if kp.id == focus:
                    return (kp.name or focus, kp.description or "")
        return (focus, "")

    async def _interact(self, stream, context, pending) -> str | None:
        """Present the open question and return ``None``.

        The candidate presents the pose through the generic stream primitive
        (no ``runtime.stream`` import — Architecture Gate) and never awaits a
        reply here: the learner's answer arrives on a LATER execution through
        ``resume_input`` / the user message, which :meth:`_incoming_answer` then
        grades deterministically.  This keeps the graph mode-agnostic and free
        of runtime-internal event types.
        """
        if pending is None:
            return None
        try:
            await stream.content(
                f"Question: {pending.prompt}",
                source="teaching_graph.candidate",
                stage="responding",
            )
        except Exception:  # noqa: BLE001 - a non-rendering stream must not fail the loop
            return None
        return None

    async def _delegate_content(self, agent_loop, context, stream, deps, decision) -> bool:
        """Let the Agent Runtime render the decided content action.

        The graph has already *chosen* the action; the runtime only fills the
        learner-facing content (streaming / usage / budget stay on the runtime).
        A scoped ``graph_directive`` is passed so the LLM cannot re-decide the
        pedagogical flow. Returns ``True`` when the content pass rendered (no
        exception), ``False`` when the runtime crashed — a failed render must
        not advance the learner or emit a follow-up assessment.
        """
        directive = {
            "action": decision.action,
            "focus_node_id": decision.focus_node_id,
            "strategy": decision.strategy,
            "reason": decision.reason,
        }
        context.metadata["graph_directive"] = directive
        # The graph is authoritative for the flow — do not mount the deciding
        # mastery tools for a content pass.
        deps = dict(deps)
        deps.setdefault("graph_directive", directive)
        deps["disable_mastery_flow"] = True
        try:
            await agent_loop.run(
                context=context,
                stream=stream,
                language=str(getattr(context, "language", "en")),
                **deps,
            )
        except Exception as exc:  # noqa: BLE001 - keep the graph resilient
            logger.error("Teaching content pass failed: %s", exc, exc_info=True)
            return False
        return True


def _hex(n: int) -> str:
    import uuid

    return uuid.uuid4().hex[:n]


__all__ = ["TeachingSessionGraph", "GRAPH_TOPOLOGY"]
"""Shared Core Rubric for the Phase 1 Teaching Behavior Evaluators.

Canonical home: ``lumen/cert``.

All three Evaluator Perspectives share **this** Core Rubric when judging
whether a teaching Turn is acceptable. A Perspective may *weight* a dimension
more (e.g. Correctness highlights factual errors, Pedagogy highlights
scaffolding, Context highlights learner adaptation), but every evaluator judges
the whole turn against the same criterion set — they are not three unrelated
partial graders.

The Rubric is part of the **Evaluation Plane** and is fixed for the lifetime of
an EvaluationContext. Engineering Agent is forbidden from editing it to make a
test pass (Agent Permission Contract).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    name: str
    prompt: str


@dataclass(frozen=True, slots=True)
class SharedCoreRubric:
    """The single rubric shared by every evaluator perspective."""

    version: str = "phase1-core-1.0"
    criteria: tuple[Criterion, ...] = field(
        default_factory=lambda: (
            Criterion(
                "correctness",
                "Factual correctness & harm-safety",
                "The tutor's statements are factually correct for the subject, "
                "contain no harmful/gaslighting content, and any misconception "
                "the learner voiced is addressed correctly.",
            ),
            Criterion(
                "pedagogy_scaffolding",
                "Pedagogical scaffolding & clarity",
                "The tutor scaffolds with clarity: it gives actionable "
                "feedback/explanation appropriate to the learner's stated level, "
                "breaks ideas down without dumping jargon, and keeps each action "
                "well-scoped.",
            ),
            Criterion(
                "context_adaptation",
                "Learner/context adaptation & continuity",
                "The tutor adapts to what the learner just said, references "
                "prior dialogue consistently, does not contradict the established "
                "conversation, and advances the learning episode coherently.",
            ),
            Criterion(
                "next_action",
                "Next teaching action",
                "The turn ends with an appropriate next teaching action "
                "(feedback/explanation/scaffold/question/next exercise) that gives "
                "the learner a clear way forward rather than a dead end.",
            ),
        )
    )

    def to_prompt(self) -> str:
        lines = [
            f"Shared Core Rubric (version {self.version}) — judge the WHOLE turn "
            "against every criterion below:",
        ]
        for c in self.criteria:
            lines.append(f"- {c.id}: {c.name} — {c.prompt}")
        return "\n".join(lines)


CORE_RUBRIC = SharedCoreRubric()


__all__ = ["Criterion", "SharedCoreRubric", "CORE_RUBRIC"]
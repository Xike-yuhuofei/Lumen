"""Learner simulators for the Learn Evaluation.

Each learner answers the harness's posed questions according to a profile, so
the *same* material + engine produce different, predictable teaching paths.
Deterministic by construction — no randomness, so a run is reproducible.

Profiles (mirroring the goal's scenario list):

* :class:`StrongLearner`      — fast, independent, transfer-capable; the system
                                must not over-teach.
* :class:`WeakLearner`        — fails until scaffolding is offered, then
                                recovers; the system must escalate then fade.
* :class:`MisconceptionLearner` — fluent but holds a registered misconception;
                                  must be detected, remediated, re-verified.
* :class:`GuessingLearner`    — unstable, ~50% correct; mastery must not jump.
* :class:`ForgettingLearner`  — masters normally but fails delayed retention
                                reviews; mastery must decay / demote.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lumen.modes.learn.domain.models import KnowledgePoint

__all__ = [
    "QuizOutcome",
    "Learner",
    "StrongLearner",
    "WeakLearner",
    "MisconceptionLearner",
    "GuessingLearner",
    "ForgettingLearner",
    "StrategySensitiveLearner",
]


@dataclass(frozen=True)
class QuizOutcome:
    """What a learner does with a posed quantitative question."""

    is_correct: bool
    answer: str
    misconception: str = ""  # the registered-belief statement, when the answer is wrong


class Learner:
    """Base class: stateful per-path profile."""

    name = "learner"

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._remediated: set[str] = set()  # kp ids whose misconception was remediated
        self._plan_actions: list[str] = []

    # ── observation hooks (the harness calls these each round) ──────────

    def on_plan(self, action: str, focus: str) -> None:
        """Observe a plan decision (focus may be a misconception node id)."""
        self._plan_actions.append(action)

    def on_remediation(self, kp_id: str) -> None:
        """Observe that the engine remediated a misconception on *kp_id*."""
        self._remediated.add(kp_id)

    # ── decision points ─────────────────────────────────────────────────

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        """Answer a quantitative question about *kp*."""
        raise NotImplementedError

    def qualitative(self, kp: KnowledgePoint) -> bool:
        """Whether the learner's Feynman explanation of *kp* passes."""
        raise NotImplementedError

    def prefer_quiz(self, kp: KnowledgePoint) -> bool:
        """Whether the harness should probe *kp* with a graded quiz instead of
        an assess check (default False — concepts are Feynman-checked)."""
        return False

    # ── helpers ─────────────────────────────────────────────────────────

    def _bump(self, kp_id: str) -> int:
        self._attempts[kp_id] = self._attempts.get(kp_id, 0) + 1
        return self._attempts[kp_id]

    def _misconception_of(self, kp: KnowledgePoint) -> dict | None:
        return kp.misconceptions[0] if kp.misconceptions else None


class StrongLearner(Learner):
    """Answers correctly and independently on the first try, including
    transfer questions; passes every qualitative check."""

    name = "strong"

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        self._bump(kp.id)
        return QuizOutcome(is_correct=True, answer=kp.answer)

    def qualitative(self, kp: KnowledgePoint) -> bool:
        return True


class WeakLearner(Learner):
    """Needs scaffolding: fails a quantitative point until the engine has
    escalated (roughly 3+ attempts), then succeeds consistently. Qualitative
    checks fail the first time, pass on retry after re-teaching."""

    name = "weak"
    # fails before this many attempts on a quantitative point
    _QUANT_BREAKPOINT = 3

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        n = self._bump(kp.id)
        if n >= self._QUANT_BREAKPOINT:
            return QuizOutcome(is_correct=True, answer=kp.answer)
        return QuizOutcome(is_correct=False, answer=f"我对 {kp.name} 还不太确定")

    def qualitative(self, kp: KnowledgePoint) -> bool:
        n = self._bump(kp.id)
        # second explanation (after re-teaching) is good enough
        return n >= 2


class MisconceptionLearner(Learner):
    """Fluent but holds the kp's registered misconception: answers wrong with
    the misconception belief while it is un-remediated, correctly afterwards."""

    name = "misconception"

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        self._bump(kp.id)
        mis = self._misconception_of(kp)
        if mis is not None and kp.id not in self._remediated:
            return QuizOutcome(
                is_correct=False, answer=mis["statement"], misconception=mis["statement"]
            )
        return QuizOutcome(is_correct=True, answer=kp.answer)

    def qualitative(self, kp: KnowledgePoint) -> bool:
        self._bump(kp.id)
        mis = self._misconception_of(kp)
        if mis is not None and kp.id not in self._remediated:
            return False
        return True

    def prefer_quiz(self, kp: KnowledgePoint) -> bool:
        # While a misconception is un-remediated, probe with a graded quiz so
        # the misconception answer is actually matched and recorded (a failed
        # explanation alone cannot be matched to a registered misconception).
        return self._misconception_of(kp) is not None and kp.id not in self._remediated


class GuessingLearner(Learner):
    """Alternates right/wrong — occasionally correct but never stable; must
    never cross the mastery gate on luck."""

    name = "guessing"

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        n = self._bump(kp.id)
        if n % 2 == 1:  # odd attempts are lucky hits
            return QuizOutcome(is_correct=True, answer=kp.answer)
        return QuizOutcome(is_correct=False, answer=f"猜测：{kp.name} 大概是错的")

    def qualitative(self, kp: KnowledgePoint) -> bool:
        n = self._bump(kp.id)
        return n % 2 == 1


class ForgettingLearner(Learner):
    """Masters normally while learning, but fails delayed retention: any
    question the engine poses as spaced-repetition review is answered wrong
    (once forgotten), so mastery must decay and the point must be re-taught."""

    name = "forgetting"

    def __init__(self, *, failure_rate: float = 1.0) -> None:
        super().__init__()
        self._failure_rate = failure_rate

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        # review questions are distinguished by the harness via question_kind
        if question_kind == "review":
            self._bump(kp.id)
            return QuizOutcome(is_correct=False, answer=f"忘了 {kp.name} 的内容")
        self._bump(kp.id)
        return QuizOutcome(is_correct=True, answer=kp.answer)

    def qualitative(self, kp: KnowledgePoint) -> bool:
        self._bump(kp.id)
        return True


class StrategySensitiveLearner(Learner):
    """A more *realistic* learner the phase-4c architecture experiment asks for.

    Models the behaviours the goal lists — uncertain responses, a stable /
    interpretable misconception, and a measurable reaction to *which* teaching
    strategy it receives — while staying deterministic and reproducible:

    * **uncertain responses** — reality is not attempt-count-gated like
      ``WeakLearner``: correctness is a seeded probability that only *rises*
      when the engine actually **teaches** the point (``explain`` /
      ``practice`` / ``review`` / ``remediate_misconception``).  Being quizzed
      again without any new teaching keeps the learner near guessing level, so
      a strategy of "drill until it sticks" cannot fake mastery.
    * **stable misconception** — reuses the registered-belief mechanism: while
      un-remediated it answers wrong with the misconception's statement, and
      ``prefer_quiz`` surfaces it as a graded probe so remediation is reachable
      (exactly the engine's detection seam).
    * **strategy / scaffold sensitivity** — success probability is
      ``base_skill + STRATEGY_STEP * taught``, so *how much teaching was
      delivered* (the strategy) is the single lever that moves the learner's
      mastery, and a learner that is taught only after it has already failed
      must actually receive the teaching before it recovers.

    Seeded (``random.Random(seed)``) so every A and B cell is reproducible; a
    fixed seed + identical call order yields identical transcripts, and that is
    the property the phase-4c matrix asserts between the two candidates.
    """

    name = "strategy_sensitive"
    #: Success probability added per *teaching* exposure of a knowledge point.
    STRATEGY_STEP = 0.2
    #: Base success probability before any teaching (assessment-only ≈ guessing).
    DEFAULT_BASE_SKILL = 0.4
    #: Teaching actions that consolidate (``on_plan`` focus may be a kp or a
    #: ``"__mis"`` misconception node id).
    _TEACHING_ACTIONS = frozenset(
        {"explain", "practice", "review", "remediate_misconception"}
    )

    def __init__(self, *, seed: int = 0, base_skill: float = DEFAULT_BASE_SKILL) -> None:
        super().__init__()
        self._rng = random.Random(seed)
        self._base_skill = base_skill
        #: teaching-exposure count per knowledge point id.
        self._taught: dict[str, int] = {}

    @staticmethod
    def _kp_id(focus: str) -> str:
        return focus.split("__mis", 1)[0] if "__mis" in focus else focus

    def on_plan(self, action: str, focus: str) -> None:
        super().on_plan(action, focus)
        if action in self._TEACHING_ACTIONS and focus:
            kp = self._kp_id(focus)
            self._taught[kp] = self._taught.get(kp, 0) + 1

    def _success_prob(self, kp: KnowledgePoint) -> float:
        taught = self._taught.get(kp.id, 0)
        return min(1.0, self._base_skill + self.STRATEGY_STEP * taught)

    def _draw(self, kp: KnowledgePoint) -> bool:
        return self._rng.random() < self._success_prob(kp)

    def quiz(self, kp: KnowledgePoint, *, question_kind: str = "recall") -> QuizOutcome:
        self._bump(kp.id)
        mis = self._misconception_of(kp)
        if mis is not None and kp.id not in self._remediated:
            return QuizOutcome(
                is_correct=False, answer=mis["statement"], misconception=mis["statement"]
            )
        if self._draw(kp):
            return QuizOutcome(is_correct=True, answer=kp.answer)
        return QuizOutcome(is_correct=False, answer=f"我对 {kp.name} 还不确定")

    def qualitative(self, kp: KnowledgePoint) -> bool:
        self._bump(kp.id)
        mis = self._misconception_of(kp)
        if mis is not None and kp.id not in self._remediated:
            return False
        return self._draw(kp)

    def prefer_quiz(self, kp: KnowledgePoint) -> bool:
        return self._misconception_of(kp) is not None and kp.id not in self._remediated


def build_learner(learner_name: str) -> Learner:
    """Instantiate a learner by its canonical name (for the benchmark runner)."""
    table = {
        cls.name: cls
        for cls in (
            StrongLearner,
            WeakLearner,
            MisconceptionLearner,
            GuessingLearner,
            ForgettingLearner,
            StrategySensitiveLearner,
        )
    }
    if learner_name not in table:
        raise KeyError(f"unknown learner: {learner_name!r}")
    cls = table[learner_name]
    return cls(seed=0) if cls is StrategySensitiveLearner else cls()

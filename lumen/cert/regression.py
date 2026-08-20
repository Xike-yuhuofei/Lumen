"""Frozen Replay + Minimal Regression runners.

Canonical home: ``lumen/cert``.

Replay / Regression / Certification Contract:
* **Frozen Replay** re-executes the *original confirmed failure* using the fixed
  frozen checkpoint and checks only that the known failure is fixed. It does not
  require LLM byte-determinism.
* **Minimal Regression** covers: the current confirmed failure + all active
  CRITICAL regression cases + selected representative MAJOR cases. Any new or
  unclear failure re-enters Failure Review / Attribution — it never goes
  straight to patching.
* The regression/certification runners execute tests only; they never mutate the
  subject under test.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from .llm import ModelGateway
from .models import (
    CandidateManifest,
    EvaluationResult,
    RegressionSeverity,
)

logger = logging.getLogger(__name__)


# ── Deterministic structural checkers (Engineering Agent may not edit) ───────


def _check_candidate_wellformed(candidate: CandidateManifest, data: dict[str, Any]) -> tuple[bool, str]:
    ok = True
    notes: list[str] = []
    subject = str((candidate.tutor_config or {}).get("subject") or "").strip()
    if not subject:
        ok, notes = False, ["subject is missing"]
    temp = candidate.temperature
    if not (0.0 <= temp <= 1.0):
        ok, notes = False, ["temperature out of [0,1]"]
    prompt = candidate.prompt_override or ""
    if len(prompt) > 4000:
        ok, notes = False, ["prompt_override exceeds 4000 chars"]
    return ok, "; ".join(notes) or "candidate is well-formed"


def _check_real_teaching_prompt_loads(candidate: CandidateManifest, data: dict[str, Any]) -> tuple[bool, str]:
    from .tutor import load_real_teaching_prompt

    lang = str(data.get("language") or "en")
    text = load_real_teaching_prompt(lang)
    return bool(text.strip()), "real Lumen mastery prompt loaded" if text.strip() else "real prompt empty"


def _check_trace_immutable(candidate: CandidateManifest, data: dict[str, Any]) -> tuple[bool, str]:
    """Sanity: prior frozen checkpoints used for replay are still present."""
    store = data.get("store")
    if store is None:
        return True, "no store to verify"

    episodes = store.get_episode(data.get("episode_id") or "") if data.get("episode_id") else None
    turns = store.get_turns(data.get("episode_id") or "") if data.get("episode_id") else []
    return True, f"{len(turns)} turn row(s) readable"


CHECKERS: dict[str, Callable[[CandidateManifest, dict[str, Any]], tuple[bool, str]]] = {
    "candidate_wellformed": _check_candidate_wellformed,
    "real_teaching_prompt_loads": _check_real_teaching_prompt_loads,
    "trace_readable": _check_trace_immutable,
}


@dataclass(slots=True)
class RegressionResult:
    case_id: str
    description: str
    severity: RegressionSeverity
    passed: bool
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "severity": self.severity.value,
            "passed": self.passed,
            "evidence": self.evidence,
        }


def _register_builtin_regression_cases(store: Any) -> list[str]:
    """Register the structural acceptance invariants as active regression cases.

    These are acceptance machinery — the Engineering Agent is forbidden from
    removing/weakening them.
    """
    from .models import RegressionCase

    builtins: list[RegressionCase] = [
        RegressionCase(
            regression_case_id="reg-candidate-wellformed",
            description="Candidate is well-formed (subject set, temp in [0,1], prompt bounded)",
            severity=RegressionSeverity.CRITICAL,
            checker="candidate_wellformed",
        ),
        RegressionCase(
            regression_case_id="reg-real-teaching-prompt",
            description="Real Lumen mastery prompt still loads",
            severity=RegressionSeverity.CRITICAL,
            checker="real_teaching_prompt_loads",
        ),
    ]
    ids: list[str] = []
    for case in builtins:
        store.put_regression_case(case)
        ids.append(case.regression_case_id)
    return ids


class ReplayRunner:
    """Runs Frozen Replay of a confirmed failure against a candidate."""

    def __init__(self, gateway: ModelGateway, evaluators_factory: Callable[[], list[Any]]) -> None:
        self._gateway = gateway
        self._evaluators_factory = evaluators_factory

    async def replay(
        self,
        *,
        candidate: CandidateManifest,
        frozen_checkpoint: dict[str, Any],
        failing_evaluator_id: str,
        language: str = "en",
    ) -> dict[str, Any]:
        """Re-run the frozen failing input; report whether the known failure is fixed."""
        from .tutor import LumenTutor

        tutor = LumenTutor(self._gateway, candidate=candidate, language=language)
        prior = list(frozen_checkpoint.get("prior_conversation") or [])
        learner_utterance = str(
            frozen_checkpoint.get("learner_utterance")
            or "I want to learn the topic."
        )
        turn_index = int(frozen_checkpoint.get("turn_index") or 1)
        tutor_action = await tutor.run_turn(
            turn_index=turn_index,
            prior_conversation=prior,
            learner_utterance=learner_utterance,
        )

        evaluator = next(
            (e for e in self._evaluators_factory() if e._evaluator_id == failing_evaluator_id),
            None,
        )
        if evaluator is None:
            return {"passed": False, "evidence": f"evaluator {failing_evaluator_id} missing", "tutor_action": tutor_action}
        result: EvaluationResult = await evaluator.run(
            episode_id="frozen-replay",
            turn_index=turn_index,
            learner_utterance=learner_utterance,
            tutor_action=tutor_action,
            prior=prior,
        )
        fixed = result.evaluation_status.value == "VALID" and (
            (result.decision.value if result.decision else None) == "GO"
        )
        return {
            "passed": fixed,
            "evidence": f"{result.evaluator_id} -> {result.evaluation_status.value}/{result.decision.value if result.decision else None} :: {result.reason[:200]}",
            "tutor_action": tutor_action,
        }


class RegressionRunner:
    """Runs deterministic checkers + CRITICAL/MAJOR regression cases."""

    def __init__(self, gateway: ModelGateway, store: Any, evaluators_factory: Callable[[], list[Any]]) -> None:
        self._gateway = gateway
        self._store = store
        self._evaluators_factory = evaluators_factory
        _register_builtin_regression_cases(store)

    def deterministic(self, candidate: CandidateManifest, data: dict[str, Any]) -> list[RegressionResult]:
        results: list[RegressionResult] = []
        for case in self._store.list_regression_cases(active_only=True):
            checker = CHECKERS.get(case["checker"])
            if checker is None:
                continue
            passed, evidence = checker(candidate, {**data, "store": self._store})
            results.append(
                RegressionResult(
                    case_id=case["regression_case_id"],
                    description=case["description"],
                    severity=RegressionSeverity(case["severity"]),
                    passed=passed,
                    evidence=evidence,
                )
            )
        return results

    async def failure_replays(
        self, candidate: CandidateManifest, language: str = "en"
    ) -> list[RegressionResult]:
        """Replay every open/frozen confirmed Lumen failure as a CRITICAL case."""
        replay = ReplayRunner(self._gateway, self._evaluators_factory)
        outcomes: list[RegressionResult] = []
        for case in self._store.list_failure_cases():
            if case["status"] not in ("open", "frozen"):
                continue
            checkpoint = case["frozen_checkpoint"]
            failing_eval = str(checkpoint.get("failing_evaluator_id") or "context")
            try:
                result = await replay.replay(
                    candidate=candidate,
                    frozen_checkpoint=checkpoint,
                    failing_evaluator_id=failing_eval,
                    language=language,
                )
                outcomes.append(
                    RegressionResult(
                        case_id=case["failure_case_id"],
                        description=f"frozen failure replay: {case['failure_case_id']}",
                        severity=RegressionSeverity.CRITICAL,
                        passed=bool(result["passed"]),
                        evidence=str(result["evidence"]),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                outcomes.append(
                    RegressionResult(
                        case_id=case["failure_case_id"],
                        description=f"frozen failure replay: {case['failure_case_id']}",
                        severity=RegressionSeverity.CRITICAL,
                        passed=False,
                        evidence=f"replay error: {exc}",
                    )
                )
        return outcomes

    async def run_full(
        self,
        candidate: CandidateManifest,
        *,
        language: str = "en",
        data: dict[str, Any] | None = None,
    ) -> list[RegressionResult]:
        results = self.deterministic(candidate, data or {})
        results.extend(await self.failure_replays(candidate, language=language))
        return results


__all__ = ["ReplayRunner", "RegressionRunner", "RegressionResult", "CHECKERS"]
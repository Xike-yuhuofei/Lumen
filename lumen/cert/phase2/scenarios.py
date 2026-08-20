"""Phase 2A — discriminating teaching scenarios & candidate strategies.

Canonical home: ``lumen/cert/phase2``.

Phase 2A compares the **Frozen Baseline** (Phase 1 real Lumen mastery prompt)
against new Teaching Strategies across a small set of **discriminating**
scenarios. A scenario is deliberately chosen (subject / goal / knowledge-points
/ learner profile) so that different teaching strategies diverge in behaviour —
they are topped-up to expose gaps in *diagnosis*, *misconception correction*,
*socratic elicitation*, *scaffolding* and *continuity* rather than being easy
pass-for-everyone turns.

Constraint (from the Phase 1 freeze): the only things a Candidate may vary are
``prompt_override`` (the teaching prompt) and ``temperature`` — never the Rubric /
Evaluators / Simulator / Regression cases. The `scenario` (``tutor_config``) is an
experimental **condition**; every strategy under a scenario uses the *same*
scenario so the comparison is fair and the trajectory/evaluation context ids
match (only the immutable turn trace legitimately differs).

Each Candidate change always produces a fresh ``effective_candidate_id`` derived
from the content digest of ``(tutor_config, prompt_override, temperature)`` — no
candidate is ever silently overwritten.
"""

from __future__ import annotations

from typing import Any

from ..models import CandidateManifest, content_digest

#: Every candidate/strategy in this phase shares ONE Evaluation Plane config so
#: the evaluator (Rubric) is not touched by the experiment.
EVAL_CONFIG: dict[str, Any] = {
    "rubric_version": "phase1-core-1.0",
    "perspectives": ["correctness", "pedagogy", "context"],
}

#: The Frozen Baseline strategy id — this maps to ``prompt_override=""`` so the
#: candidate uses the real Lumen mastery prompt (identical to Phase 1).
BASELINE_STRATEGY_ID = "baseline"
DEFAULT_MAX_TURNS = 10


# ── Candidate strategies (teaching prompts) ──────────────────────────────────


_DIAGNOSE_FIRST = (
    "STRATEGY: Diagnose-before-you-teach.\n"
    "Before adding new content, infer the learner's current understanding from "
    "their latest message. If they voice a misconception or a faulty prior "
    "assumption, address that misconception explicitly and correct it before "
    "building on it. Teach one scoped idea at a time, then check the learner "
    "used it correctly before the next step. Reference what the learner "
    "actually said, do not lecture past their error."
)

_SOCRATIC = (
    "STRATEGY: Question-driven (Socratic) teaching.\n"
    "Teach primarily by asking short, well-scoped questions that get the "
    "learner to reason aloud, rather than by long explanations. Give immediate, "
    "targeted feedback on their answer. When they err, guide them to "
    "re-derive the correct idea with a cue instead of simply stating the "
    "answer. Keep each action short so the learner produces the next utterance."
)

#: Strategy id -> (additive directive, fixed temperature). ``baseline`` keeps
#: ``prompt_override=""`` (real prompt), so its directive is empty.
STRATEGIES: dict[str, dict[str, Any]] = {
    BASELINE_STRATEGY_ID: {"directive": "", "temperature": 0.2},
    "diagnose-first": {"directive": _DIAGNOSE_FIRST, "temperature": 0.2},
    "socratic-questions": {"directive": _SOCRATIC, "temperature": 0.2},
}

#: Report/run order: baseline first, then new strategies.
STRATEGY_ORDER: list[str] = [
    BASELINE_STRATEGY_ID,
    "diagnose-first",
    "socratic-questions",
]


# ── Scenario registry ────────────────────────────────────────────────────────


#: Scenario A — conceptual-heavy, misconception-ripe (Go concurrency).
SCENARIO_GO: dict[str, Any] = {
    "id": "go-concurrency",
    "tutor_config": {
        "subject": "Concurrency in Go",
        "goal": "Understand goroutines, channels, and the Go memory model "
                "(happens-before and data races).",
        "knowledge_points": [
            "goroutines are lightweight, multiplexed, not OS threads",
            "channels are typed for synchronization and data flow, not a generic queue",
            "sending on an unbuffered channel synchronizes sender and receiver",
            "the happens-before edge and the race detector / data-race model",
        ],
        "learner_profile": "an experienced Java developer new to Go who starts "
            "from strong-but-misaligned assumptions (equates goroutines to OS "
            "threads, treats channels as a generic queue), may voice these "
            "misconceptions, and replies naturally in 1-3 sentences",
        "path_id": "",
    },
}

#: Scenario B — confidence-bias ripe (sampling & bias / correlation).
SCENARIO_SAMPLING: dict[str, Any] = {
    "id": "sampling-bias",
    "tutor_config": {
        "subject": "Sampling and bias in statistics",
        "goal": "Understand why a random representative sample can beat a "
                "larger non-representative one, and how to avoid coverage bias "
                "and mistaking correlation for causation.",
        "knowledge_points": [
            "a random representative sample can beat a larger biased sample",
            "coverage / sampling bias and why 'more data' does not fix bias",
            "correlation does not imply causation (confounding variables)",
            "larger samples only shrink variance when the estimate is unbiased",
        ],
        "learner_profile": "a confident adult who confidently holds the common "
            "misconceptions that a bigger sample is always more accurate and "
            "that correlation proves causation, may assert these out loud, and "
            "replies naturally in 1-3 sentences",
        "path_id": "",
    },
}

#: Order of scenarios for the run matrix.
SCENARIOS: dict[str, dict[str, Any]] = {
    SCENARIO_GO["id"]: SCENARIO_GO,
    SCENARIO_SAMPLING["id"]: SCENARIO_SAMPLING,
}


# ── Candidate builder ────────────────────────────────────────────────────────


def join_prompt(base_prompt: str, directive: str) -> str:
    """Append a strategy directive to a base teaching prompt (additive change).

    ``baseline`` uses ``prompt_override=""`` (the real prompt is loaded by the
    Tutor) so its behaviour is identical to Phase 1. New strategies are the real
    prompt PLUS the directive, so the only controlled variable is the strategy.
    """
    directive = (directive or "").strip()
    if not directive:
        return ""
    base = (base_prompt or "").strip()
    return base + "\n\n" + directive if base else directive


def build_candidate(
    *,
    strategy: str,
    scenario: dict[str, Any],
    base_prompt: str = "",
) -> CandidateManifest:
    """Build a Candidate for ``strategy`` under ``scenario``.

    The scenario's ``tutor_config`` is shared by every strategy (fair
    condition). ``prompt_override`` = real-prompt + strategy directive for new
    strategies, and ``""`` for the Frozen Baseline. A new content digest always
    yields a new ``effective_candidate_id``.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}")
    cfg = dict(scenario["tutor_config"])
    # Experiment metadata tag (does not affect the trajectory context digest,
    # which is derived only from the subject).
    cfg["strategy_tag"] = strategy
    directive = STRATEGIES[strategy]["directive"]
    temperature = float(STRATEGIES[strategy]["temperature"])
    prompt_override = (
        "" if strategy == BASELINE_STRATEGY_ID else join_prompt(base_prompt, directive)
    )
    payload = {
        "tutor_config": cfg,
        "prompt_override": prompt_override,
        "temperature": temperature,
    }
    digest = content_digest(payload)
    cid = f"p2a-{scenario['id']}-{strategy}-{digest[:16]}"
    return CandidateManifest(
        effective_candidate_id=cid,
        parent_candidate_id=None,
        content_digest=digest,
        tutor_config=cfg,
        prompt_override=prompt_override,
        temperature=temperature,
    )


def load_real_base_prompt(language: str = "en") -> str:
    """Real Lumen teaching prompt used as the base for strategy overrides."""
    from ..tutor import load_real_teaching_prompt

    return load_real_teaching_prompt(language)


__all__ = [
    "EVAL_CONFIG",
    "BASELINE_STRATEGY_ID",
    "DEFAULT_MAX_TURNS",
    "STRATEGIES",
    "STRATEGY_ORDER",
    "SCENARIOS",
    "SCENARIO_GO",
    "SCENARIO_SAMPLING",
    "join_prompt",
    "build_candidate",
    "load_real_base_prompt",
]
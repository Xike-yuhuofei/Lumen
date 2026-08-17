"""Assessment — deterministic answer grading and pending question state.

Grading (``grade_answer`` / ``classify_error``) is deterministic and fail-closed:
an attempt is never recorded correct without a stored expected answer.  The
pending-question module projects the persisted ``PendingQuestion`` into the
learner-facing contract (never exposing ``expected_answer``).
"""

from lumen.modes.learn.assessment.grading import classify_error, grade_answer
from lumen.modes.learn.assessment.pending import (
    OPTION_PREFIX_RE,
    PublicPendingOption,
    PublicPendingQuestion,
    format_options,
    has_option_bodies,
    parse_options,
    public_pending_question,
    resolve_answer,
    resolve_choice_submission,
)

__all__ = [
    "OPTION_PREFIX_RE",
    "PublicPendingOption",
    "PublicPendingQuestion",
    "classify_error",
    "format_options",
    "grade_answer",
    "has_option_bodies",
    "parse_options",
    "public_pending_question",
    "resolve_answer",
    "resolve_choice_submission",
]

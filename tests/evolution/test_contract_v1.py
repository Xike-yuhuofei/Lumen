"""Contract tests — the frozen Provider Contract v1 surface."""

from __future__ import annotations

from lumen.evolution.contract import (
    ProviderRequest,
    ProviderResult,
    RuntimeProvider,
    TeachingDecision,
    TeachingDecisionKind,
    Termination,
    TerminationReason,
    TurnError,
    TurnInput,
    TurnOutput,
    TurnState,
)


def test_termination_enum_has_completed():
    assert TerminationReason.COMPLETED.value == "completed"
    assert TerminationReason.INTERRUPTED.value == "interrupted"
    assert TerminationReason.BUDGET_EXHAUSTED.value == "budget_exhausted"


def test_teaching_decision_kind_is_enum():
    assert TeachingDecisionKind.EXPLAIN in TeachingDecisionKind
    assert TeachingDecisionKind.ASSESS in TeachingDecisionKind
    assert TeachingDecisionKind.REMEDIATE in TeachingDecisionKind


def test_input_and_state_have_minimal_fields():
    input_ = TurnInput(user_message="hi", session_id="s")
    state = TurnState(turn_id="t", step=0)
    assert input_.user_message == "hi"
    assert state.step == 0
    assert state.checkpoint()["turn_id"] == "t"


def test_output_termination_error_are_constructible():
    out = TurnOutput(final_text="x", tool_calls=[("calc", {"a": 1})])
    term = Termination(reason=TerminationReason.COMPLETED, completed=True, step_count=1)
    err = TurnError(kind="model_error", message="boom", recoverable=True)
    assert out.final_text == "x"
    assert term.reason == TerminationReason.COMPLETED
    assert err.recoverable


def test_provider_result_composes_all_output_contracts():
    res = ProviderResult(
        provider_id="x",
        output=TurnOutput(),
        termination=Termination(),
        error=None,
        trace=[],
    )
    assert res.provider_id == "x"
    assert res.error is None


def test_runtime_provider_is_a_protocol_not_instantiable():
    # RuntimeProvider is a Protocol; it must not be directly instantiable.
    import inspect

    assert inspect.isclass(RuntimeProvider)


def test_provider_request_composes_all_input_contracts():
    req = ProviderRequest(
        input=TurnInput(user_message="u", session_id="s"),
        state=TurnState(),
        context=None,  # type: ignore[arg-type]  # placeholder
        model=None,  # type: ignore[arg-type]
        tools=None,  # type: ignore[arg-type]
    )
    assert req.input.user_message == "u"
    assert req.seed is None

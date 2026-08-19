"""P0 — Legacy Provider: the behaviour reference / regression oracle.

This is a *contract-native* re-implementation of the legacy loop's observable
semantics driven through the unified ``Model`` / ``ToolRuntime`` seams.  It is
NOT the production ``AgenticChatPipeline`` (which remains unchanged and is the
true production Provider).  P0 exists so every provider — including future
LangGraph / native ones — has a deterministic behaviour baseline to match: the
classic agentic loop

    model(tools) → if tool_calls: dispatch each via ToolRuntime, append results,
                   call model again → else final answer; stop.

The production pipeline is intentionally NOT modified, wrapped, or replaced by
this provider — P0 is a companion oracle, not the production binding.
"""

from __future__ import annotations

from typing import Any

from lumen.evolution.contract import (
    ProviderRequest,
    ProviderResult,
    RuntimeProvider,
    Termination,
    TerminationReason,
    TraceEvent,
    TurnError,
    TurnOutput,
)
from lumen.evolution.models import _text, _tool_calls


class LegacyProvider(RuntimeProvider):
    """The contract-native legacy-loop oracle."""

    provider_id = "legacy"

    def __init__(
        self,
        *,
        max_steps: int = 10,
        emit_stream: bool = True,
    ) -> None:
        self._max_steps = max_steps
        self._emit_stream = emit_stream

    async def run(self, request: ProviderRequest) -> ProviderResult:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": request.input.user_message}
        ] + list(request.input.conversation_history)
        state = request.state
        trace: list[TraceEvent] = []
        tool_calls_log: list[tuple[str, dict[str, Any]]] = []
        streamed_chars = 0
        final_text = ""
        error: TurnError | None = None
        reason = TerminationReason.COMPLETED

        for step in range(self._max_steps):
            state.step = step + 1
            model_out = await request.model.generate(
                messages,
                tools=request.tools.build_schemas(),
                seed=request.seed,
                **(request.config or {}),
            )
            trace.append(TraceEvent(step=step + 1, kind="model_call", data={"round": step + 1}))
            calls = _tool_calls(model_out)
            text = _text(model_out)

            if not calls:
                # Final answer (or the last script step repeats → plain text).
                if text:
                    final_text = text
                    streamed_chars += len(text)
                trace.append(TraceEvent(step=step + 1, kind="state", data={"state": "final"}))
                break

            # Dispatch each requested tool call through the ToolRuntime.
            for call in calls:
                name = call.get("name")
                args = dict(call.get("args") or {})
                if self._emit_stream:
                    pass  # stream events are captured via TraceEvent; provider stays framework-agnostic
                try:
                    result = await request.tools.execute(name, **args)
                except Exception as exc:  # noqa: BLE001
                    result = f"Error: {exc}"
                    trace.append(
                        TraceEvent(
                            step=step + 1,
                            kind="error",
                            data={"tool": name, "error": str(exc)},
                        )
                    )
                tool_calls_log.append((name, args))
                trace.append(
                    TraceEvent(
                        step=step + 1,
                        kind="tool_call",
                        data={"name": name, "args": args, "result": str(result)},
                    )
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{step}", "name": name, "args": args}],
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": f"call-{step}", "content": str(result)}
                )
        else:
            reason = TerminationReason.STEP_LIMIT
            final_text = final_text or _text(model_out)  # type: ignore[name-defined]

        termination = Termination(
            reason=reason,
            completed=reason == TerminationReason.COMPLETED,
            step_count=state.step,
        )
        return ProviderResult(
            provider_id=self.provider_id,
            output=TurnOutput(
                final_text=final_text,
                tool_calls=tool_calls_log,
                streamed_chars=streamed_chars,
            ),
            termination=termination,
            error=error,
            trace=trace,
        )


__all__ = ["LegacyProvider"]

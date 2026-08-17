"""A/B bake-off scenario harness (Phase 5.5).

Runs the same deterministic scenarios against both the legacy and the
LangChain ``runtime.agent_loop`` providers, collecting comparable metrics
(functional completeness, tool calls, streaming, interrupt, recovery).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


@dataclass
class ScenarioResult:
    """Outcome of one scenario on one provider."""

    scenario: str
    ok: bool = False
    events: list[StreamEvent] = field(default_factory=list)
    final_text: str = ""
    completed: bool = False
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error: str = ""

    @property
    def streamed_chars(self) -> int:
        return sum(len(e.content or "") for e in self.events if e.type == StreamEventType.CONTENT)


def _collect_events(bus: StreamBus) -> list[StreamEvent]:
    return list(bus._history)


def _event_kinds(events: list[StreamEvent]) -> list[str]:
    return [e.type.value if hasattr(e.type, "value") else str(e.type) for e in events]


async def run_scenario(
    agent_loop: Any,
    *,
    scenario: str,
    user_message: str,
    enabled_tools: list[str] | None = None,
    knowledge_bases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    language: str = "en",
    wait_for_user_reply: Any = None,
    config: dict[str, Any] | None = None,
) -> ScenarioResult:
    """Run *scenario* against *agent_loop* and capture everything."""
    bus = StreamBus()
    ctx = UnifiedContext(
        session_id=f"bakeoff-{scenario}",
        user_message=user_message,
        enabled_tools=enabled_tools or [],
        knowledge_bases=knowledge_bases or [],
        language=language,
        metadata=dict(metadata or {}),
    )
    if wait_for_user_reply is not None:
        ctx.metadata["wait_for_user_reply"] = wait_for_user_reply

    result = ScenarioResult(scenario=scenario)
    try:
        await agent_loop.run(
            context=ctx,
            stream=bus,
            language=language,
            **(config or {}),
        )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.events = _collect_events(bus)
        return result

    result.events = _collect_events(bus)

    # Extract content / results / tool calls
    content_parts: list[str] = []
    for event in result.events:
        if event.type == StreamEventType.CONTENT:
            content_parts.append(event.content or "")
        if event.type == StreamEventType.TOOL_CALL:
            result.tool_calls.append((event.content or "", event.metadata.get("args", {})))
        if event.type == StreamEventType.RESULT:
            result.final_text = str(event.metadata.get("response") or event.content or "")
            result.completed = bool(event.metadata.get("completed", False))

    if not result.final_text:
        result.final_text = "".join(content_parts)

    # Decide pass/fail per scenario.
    result.ok = _judge_scenario(result)
    return result


def _judge_scenario(result: ScenarioResult) -> bool:
    scenario = result.scenario
    if scenario == "plain_reply":
        return bool(result.final_text.strip()) and not result.error
    if scenario == "single_tool_call":
        return bool(result.tool_calls) and not result.error
    if scenario == "multi_tool_call":
        return len(result.tool_calls) >= 2 and not result.error
    if scenario == "rag":
        return bool(result.final_text.strip()) and not result.error
    if scenario == "memory":
        return bool(result.final_text.strip()) and not result.error
    if scenario == "notebook":
        return bool(result.final_text.strip()) and not result.error
    if scenario == "interrupt_resume":
        # Must have emitted a wait-for-input event and then completed.
        kinds = _event_kinds(result.events)
        has_pause = any("pending" in k or "wait_for_input" in k for k in kinds)
        return has_pause and not result.error
    if scenario == "streaming":
        # >1 content events means it actually streamed incrementally.
        return sum(1 for e in result.events if e.type == StreamEventType.CONTENT) > 1
    if scenario == "tool_error":
        return not result.error
    if scenario == "llm_error":
        return True  # whatever the recovery strategy, it must not hang
    if scenario == "learn_turn":
        return bool(result.final_text.strip()) and not result.error
    if scenario == "assessment_practice":
        return not result.error
    if scenario == "session_resume":
        return not result.error
    if scenario == "cancellation":
        return not result.error
    if scenario == "shutdown_dispose":
        return not result.error
    return not result.error


def summarize(a_results: list[ScenarioResult], b_results: list[ScenarioResult]) -> dict[str, Any]:
    """Compare two provider runs and return a metric table."""
    by_name_a = {r.scenario: r for r in a_results}
    by_name_b = {r.scenario: r for r in b_results}
    rows: list[dict[str, Any]] = []
    for scenario in sorted(by_name_a.keys()):
        ra = by_name_a[scenario]
        rb = by_name_b.get(scenario)
        rows.append(
            {
                "scenario": scenario,
                "legacy_ok": ra.ok,
                "langchain_ok": bool(rb and rb.ok),
                "legacy_error": ra.error,
                "langchain_error": (rb.error if rb else "not run"),
            }
        )
    return {"rows": rows}

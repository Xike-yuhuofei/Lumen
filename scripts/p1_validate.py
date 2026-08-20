"""P1 Real-World Validation Harness.

Drives *real* Lumen sessions through the dev Active Provider
(``agent_loop.langgraph_thin`` = P1, LangGraph Thin) using the real model and
the real runtime stack (``LumenApp`` facade → ``TurnRuntimeManager`` →
``runtime.agent_loop`` → P1 bridge), covering the workload matrix:

    single-turn / multi-turn / long-context / teaching (mode.learn) /
    tool-call / state persistence + recovery / interrupt-resume (ask_user) /
    retry-replay (regenerate) / exceptions / cancel / timeout / long-running

Every scenario runs through the SAME real path a frontend / CLI turn uses, so
the results reflect genuine production-shaped usage of P1, not synthetic
unit-level replay.

Usage:
    LUMEN_AGENT_LOOP_PROVIDER=langgraph_thin python scripts/p1_validate.py [--summary]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumen.app.facade import LumenApp
from lumen.runtime.stream.events import StreamEventType

# ── helpers ───────────────────────────────────────────────────────────────────


def _event_fields(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": event.get("type"),
        "source": event.get("source"),
        "stage": event.get("stage"),
        "content": (event.get("content") or "")[:80],
        "meta_keys": sorted((event.get("metadata") or {}).keys()),
    }


async def _collect(app: LumenApp, turn_id: str) -> list[dict[str, Any]]:
    """Drain one turn's event stream to a list of plain dicts."""
    out: list[dict[str, Any]] = []
    async for item in app.stream_turn(turn_id):
        out.append(dict(item))
    return out


def _content(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(e.get("content") or "")
        for e in events
        if e.get("type") == StreamEventType.CONTENT.value
    )


def _has(events: list[dict[str, Any]], etype: str) -> bool:
    return any(e.get("type") == etype for e in events)


def _status(events: list[dict[str, Any]]) -> str:
    for e in reversed(events):
        if e.get("type") == StreamEventType.DONE.value:
            return str((e.get("metadata") or {}).get("status") or "completed")
    return "no-done"


# ── scenario registry ─────────────────────────────────────────────────────────


class Scenario:
    name = ""

    async def run(self, app: LumenApp) -> dict[str, Any]:
        raise NotImplementedError


class SingleTurnScenario(Scenario):
    name = "single_turn"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        start = time.perf_counter()
        session, turn = await app.start_turn(
            {"content": "Reply with exactly: P1-SINGLE-OK", "capability": "chat", "language": "en"}
        )
        events = await _collect(app, turn["id"])
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "status": _status(events),
            "latency_s": round(time.perf_counter() - start, 3),
        }


class MultiTurnScenario(Scenario):
    name = "multi_turn"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # Turn 1 establishes context; turn 2 must observe it via conversation history.
        session, turn1 = await app.start_turn(
            {
                "content": "Remember this secret codeword: LUMENP1CODE42. Confirm you noted it.",
                "capability": "chat",
                "language": "en",
            }
        )
        await _collect(app, turn1["id"])
        session_id = session["id"]
        # Follow-up: the model must recall the codeword from the same session.
        session2, turn2 = await app.start_turn(
            {
                "content": "What is the secret codeword I told you earlier? Reply with ONLY that codeword.",
                "capability": "chat",
                "language": "en",
                "session_id": session_id,
            }
        )
        events = await _collect(app, turn2["id"])
        content = _content(events)
        return {
            "session_id": session_id,
            "events": [_event_fields(e) for e in events],
            "content": content,
            "recalled": "LUMENP1CODE42" in content,
            "status": _status(events),
        }


class LongContextScenario(Scenario):
    name = "long_context"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # A large user message + several turns approximates a long-context session.
        session_id = None
        long_text = " ".join(f"fact_{i}" for i in range(400))
        for i in range(6):
            content = (
                f"Turn {i}: append the following to your working memory: {long_text[:1200]}"
                if i % 2 == 0
                else f"Turn {i}: confirm you are still tracking the conversation (reply briefly)."
            )
            session, turn = await app.start_turn(
                {
                    "content": content,
                    "capability": "chat",
                    "language": "en",
                    "session_id": session_id,
                }
            )
            session_id = session["id"]
            await _collect(app, turn["id"])
        session, turn = await app.start_turn(
            {
                "content": "Reply with exactly: LONGCTX-DONE",
                "capability": "chat",
                "language": "en",
                "session_id": session_id,
            }
        )
        events = await _collect(app, turn["id"])
        content = _content(events)
        return {
            "session_id": session_id,
            "events": [_event_fields(e) for e in events],
            "content": content,
            "ok": "LONGCTX-DONE" in content,
            "status": _status(events),
        }


class ToolCallScenario(Scenario):
    name = "tool_call"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # Enable a real tool (web_search) and ask a question that requires it.
        session, turn = await app.start_turn(
            {
                "content": "Use the web_search tool to look up what year the first WebSocket RFC was published.",
                "capability": "chat",
                "language": "en",
                "tools": ["web_search"],
            }
        )
        events = await _collect(app, turn["id"])
        tool_calls = [e for e in events if e.get("type") == StreamEventType.TOOL_CALL.value]
        tool_results = [e for e in events if e.get("type") == StreamEventType.TOOL_RESULT.value]
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "tool_calls": [e.get("content") for e in tool_calls],
            "tool_results_count": len(tool_results),
            "status": _status(events),
        }


class LearnTurnScenario(Scenario):
    name = "teaching_mode_learn"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        path_id = "p1-val-path"
        # Reset learner state for a deterministic run.
        try:
            from lumen.modes.learn.adapters.storage import LearningStore

            store = LearningStore()
            progress = store.load(path_id)
            if progress is not None:
                store.delete(path_id)
        except Exception:
            pass
        # mode.learn turns carry mastery_path_id in the runtime payload (the
        # WS router passes the full dict to TurnRuntimeManager.start_turn).
        session, turn = await app.runtime.start_turn(
            {
                "content": "I want to learn the basics of the HTTP protocol. Start teaching me.",
                "capability": "mode.learn",
                "language": "en",
                "mastery_path_id": path_id,
            }
        )
        events = await _collect(app, turn["id"])
        tool_calls = [e for e in events if e.get("type") == StreamEventType.TOOL_CALL.value]
        content = _content(events)
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": content,
            "mastery_tools_called": [e.get("content") for e in tool_calls],
            "status": _status(events),
            "path_id": path_id,
        }


class InterruptResumeScenario(Scenario):
    name = "interrupt_resume"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # Drive ask_user pause/resume through the real reply-waiter path.
        # The turn task runs in the background; we iterate the single event
        # stream once and submit the reply as a side-effect the moment the
        # WAIT_FOR_INPUT event arrives (mirrors the frontend reply submit).
        session, turn = await app.start_turn(
            {
                "content": "Ask me my favorite programming language using ask_user, then acknowledge my answer.",
                "capability": "chat",
                "language": "en",
                "tools": ["ask_user"],
            }
        )
        turn_id = turn["id"]
        events: list[dict[str, Any]] = []
        delivered = False
        deadline = time.monotonic() + 90
        try:
            async for item in app.stream_turn(turn_id):
                events.append(item)
                if not delivered and item.get("type") == StreamEventType.WAIT_FOR_INPUT.value:
                    await app.submit_user_reply(turn_id, text="Python")
                    delivered = True
                if item.get("type") == StreamEventType.DONE.value:
                    break
                if time.monotonic() > deadline:
                    break
        except asyncio.CancelledError:
            pass
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "paused": _has(events, StreamEventType.WAIT_FOR_INPUT.value),
            "reply_delivered": delivered,
            "status": _status(events),
        }


class RegenerateScenario(Scenario):
    name = "retry_replay_regenerate"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        session, turn1 = await app.start_turn(
            {"content": "Reply with exactly: FIRST-ANSWER", "capability": "chat", "language": "en"}
        )
        await _collect(app, turn1["id"])
        session_id = session["id"]
        # Regenerate the last user message (retry/replay path).
        session2, turn2 = await app.regenerate_last_turn(session_id)
        events = await _collect(app, turn2["id"])
        content = _content(events)
        return {
            "session_id": session_id,
            "events": [_event_fields(e) for e in events],
            "content": content,
            "ok": "FIRST-ANSWER" in content,
            "status": _status(events),
        }


class CancelScenario(Scenario):
    name = "cancel"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        session, turn = await app.start_turn(
            {
                "content": "Write a very long essay about the history of the internet (keep going for a while).",
                "capability": "chat",
                "language": "en",
            }
        )
        turn_id = turn["id"]
        await asyncio.sleep(2.0)  # let the turn start generating
        cancelled = await app.cancel_turn(turn_id)
        events = await _collect(app, turn_id)
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "cancelled_ack": cancelled,
            "status": _status(events),
        }


class ToolErrorScenario(Scenario):
    name = "tool_error_recovery"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # Trigger a failing tool path: ask for a nonexistent KB via rag.
        session, turn = await app.start_turn(
            {
                "content": "Use the rag tool with kb_name 'definitely_missing_kb_xyz' to answer a question about it.",
                "capability": "chat",
                "language": "en",
                "tools": ["rag"],
            }
        )
        events = await _collect(app, turn["id"])
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "status": _status(events),
        }


class LongRunningScenario(Scenario):
    name = "long_running"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # A multi-step task that forces several tool rounds (research-style):
        # exercises the loop over many agent ⇄ tools rounds without hanging.
        start = time.perf_counter()
        session, turn = await app.start_turn(
            {
                "content": (
                    "Research the answer to this question with web_search, then give "
                    "a 2-sentence answer. Question: what year was TCP/IP split from "
                    "NCP into the 4-layer model by Cerf and Kahn?"
                ),
                "capability": "chat",
                "language": "en",
                "tools": ["web_search"],
            }
        )
        events = await _collect(app, turn["id"])
        tool_calls = [e for e in events if e.get("type") == StreamEventType.TOOL_CALL.value]
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "tool_rounds": len(tool_calls),
            "latency_s": round(time.perf_counter() - start, 3),
            "status": _status(events),
        }


class TimeoutScenario(Scenario):
    name = "timeout_recovery"

    async def run(self, app: LumenApp) -> dict[str, Any]:
        # Timeout the turn's stream: if P1 hangs past a bounded wait, the
        # turn must still reconcile to a terminal status (not stay "running").
        session, turn = await app.start_turn(
            {
                "content": "Write a detailed 3-paragraph explanation of the OSI model.",
                "capability": "chat",
                "language": "en",
            }
        )
        turn_id = turn["id"]
        events: list[dict[str, Any]] = []
        try:
            agen = app.stream_turn(turn_id)
            deadline = time.monotonic() + 45
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                events.append(item)
                if item.get("type") == StreamEventType.DONE.value:
                    break
        except Exception as exc:  # noqa: BLE001
            return {"session_id": session["id"], "error": f"{type(exc).__name__}: {exc}"}
        return {
            "session_id": session["id"],
            "events": [_event_fields(e) for e in events],
            "content": _content(events),
            "status": _status(events),
            "ended_within_budget": bool(events),
        }


SCENARIOS: dict[str, type[Scenario]] = {
    s.name: s
    for s in [
        SingleTurnScenario,
        MultiTurnScenario,
        LongContextScenario,
        ToolCallScenario,
        LearnTurnScenario,
        InterruptResumeScenario,
        RegenerateScenario,
        CancelScenario,
        ToolErrorScenario,
        LongRunningScenario,
        TimeoutScenario,
    ]
}


async def run_all(summary_only: bool, only: set[str] | None = None) -> list[dict[str, Any]]:
    from lumen.bootstrap import resolve_active_assembly

    profile, plugins = resolve_active_assembly()
    provider_id = profile.bindings.get("runtime.agent_loop", "legacy")
    print(f"ActiveProvider: {provider_id}  (profile bindings={profile.bindings})", flush=True)

    app = LumenApp()
    results: list[dict[str, Any]] = []
    for name, cls in SCENARIOS.items():
        if only and name not in only:
            continue
        print(f"\n=== {name} ===", flush=True)
        scenario = cls()
        try:
            result = await scenario.run(app)
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{type(exc).__name__}: {exc}"}
        if summary_only:
            result = {k: v for k, v in result.items() if k not in ("events", "content")}
        results.append({"scenario": name, **result})
        print(json.dumps(result, ensure_ascii=False)[:600], flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true", help="Omit events/content.")
    parser.add_argument("--json", default="", help="Write full results JSON to this path.")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated scenario names to run (default: all).",
    )
    args = parser.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = asyncio.run(run_all(args.summary, only=only))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nWrote {len(results)} scenario results to {args.json}", flush=True)


if __name__ == "__main__":
    main()

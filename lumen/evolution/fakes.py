"""Deterministic fakes for the Evolution Harness.

These are NOT framework mocks that hide runtime behaviour — they are the
control-variable seam the benchmark uses so every provider runs the same
tools / teaching / model in the same environment, reproducibly.
"""

from __future__ import annotations

from typing import Any

from lumen.evolution.contract import (
    TeachingDecision,
    TeachingDecisionKind,
    TeachingInput,
    TeachingPlugin,
    ToolRuntime,
)


class FakeToolRuntime(ToolRuntime):
    """An in-memory, deterministic ToolRuntime."""

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._tools: dict[str, Any] = dict(tools or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, name: str, fn: Any) -> None:
        self._tools[name] = fn

    def list_available(self) -> list[str]:
        return list(self._tools.keys())

    def definition(self, name: str) -> Any:
        return self._tools.get(name)

    def build_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        keys = list(self._tools.keys()) if names is None else names
        return [{"name": k, "description": "fake"} for k in keys]

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"Unknown tool: {name}")
        result = fn(**kwargs)
        if callable(getattr(result, "__await__", None)):
            result = await result
        return result


async def _calc(a: int, b: int) -> str:
    return f"{a} + {b} = {a + b}"


async def _boom() -> str:
    raise RuntimeError("boom")


async def _ask() -> str:
    return "[awaiting user reply]"


def make_standard_tools() -> FakeToolRuntime:
    """The standard deterministic tool set used by every benchmark scenario."""
    tr = FakeToolRuntime()
    tr.register("calc", _calc)
    tr.register("boom", _boom)
    tr.register("ask_user", _ask)
    return tr


class ScriptedTeaching(TeachingPlugin):
    """A deterministic Teaching Plugin.

    The script is a list of ``TeachingInput -> TeachingDecision`` outcomes.
    While the script runs, it returns the next scripted decision; afterwards it
    reports PROGRESS (a deterministic terminal teaching step).  This keeps the
    *teaching* side identical across providers, isolating the *runtime* side.
    """

    name = "scripted-teaching"

    def __init__(self, script: list[TeachingDecision] | None = None) -> None:
        self._script = list(script or [])
        self._index = 0
        self.decisions: list[TeachingDecision] = []

    def decide(self, tin: TeachingInput) -> TeachingDecision:
        if self._index < len(self._script):
            d = self._script[self._index]
        else:
            d = TeachingDecision(kind=TeachingDecisionKind.PROGRESS, strategy="advance")
        self._index += 1
        self.decisions.append(d)
        return d

    def scaffold(self, decision: TeachingDecision, context: Any) -> str:
        return f"[scaffold:{decision.kind.value}]"

    def assess(self, decision: TeachingDecision, output: Any) -> dict[str, Any]:
        return {"decision": decision.kind.value, "ok": bool(output)}


__all__ = [
    "FakeToolRuntime",
    "ScriptedTeaching",
    "make_standard_tools",
    "_calc",
    "_boom",
    "_ask",
]
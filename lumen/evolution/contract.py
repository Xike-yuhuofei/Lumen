"""Provider Contract v1 — the frozen contract all Agent Runtime Providers share.

Providers are *swap-able* units: Lumen business logic, Teaching Plugins, and
the test/benchmark system depend only on the contracts defined here, never on
a specific Runtime (Legacy / LangGraph / native).  This module is the single
Source of Truth for the boundary between an Agent Runtime and everything else.

Ten sub-contracts are frozen here:

  Input Contract       — what a turn provides (user message, session, inputs)
  State Contract       — durable, provider-independent turn/agent state
  Context Contract     — the construction/grounding context a turn executes in
  Model Contract       — the LLM handle + config (deterministic seam)
  Tool Contract        — tool surface a provider may call
  Teaching Contract    — Teaching Plugin hooks the provider may invoke
  Trace Contract       — observability / lineage the provider must emit
  Output Contract      — what a completed turn returns
  Termination Contract — how a turn ends (normal / error / interrupted / budget)
  Error Contract       — normalised error surface

The top-level :class:`RuntimeProvider` protocol composes all ten.  Every new
provider (Legacy adapter, LangGraph thin, LangGraph teaching nodes, LangGraph
dual, native loop) must implement :meth:`RuntimeProvider.run` against these
types — and must NOT be required to change Lumen upper layer / Teaching
Plugins / tests in order to be swapped in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

# ── Input Contract ─────────────────────────────────────────────────────────


@dataclass
class TurnInput:
    """Everything a provider needs to start one agentic turn."""

    user_message: str
    session_id: str
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── State Contract ─────────────────────────────────────────────────────────


@dataclass
class TurnState:
    """Durable, provider-independent state the provider mutates during a turn.

    ``snapshot`` is a JSON-able / checkpoint-able record that a provider
    writes at well-defined points so a turn can be resumed or replayed.
    """

    turn_id: str = ""
    step: int = 0
    intermediate: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def checkpoint(self) -> dict[str, Any]:
        return {"turn_id": self.turn_id, "step": self.step, "snapshot": dict(self.snapshot)}


# ── Context Contract ───────────────────────────────────────────────────────


@dataclass
class RuntimeContext:
    """Construction/grounding context a turn executes in (read-only to provider).

    Teaching policy / diagnosis / scaffolding decisions belong to Teaching
    Plugins, NOT here.  A provider treats this as fixed input.
    """

    language: str = "en"
    turn_inputs: dict[str, Any] = field(default_factory=dict)  # KB seeds, memory, personas, …
    config: dict[str, Any] = field(default_factory=dict)  # provider-agnostic runtime config


# ── Model Contract ─────────────────────────────────────────────────────────


class Model(Protocol):
    """A deterministic model seam.

    ``generate`` is the single provider-facing completion call.  Providers
    MAY wrap concrete model clients (OpenAI client, LangChain model) to this
    surface; the harness injects a *deterministic fake* for reproducible runs.
    """

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[Any] | None = None,
        seed: int | None = None,
        **kwargs: Any,
    ) -> Any: ...


@dataclass
class ModelSpec:
    """Provider-agnostic description of the model a turn uses."""

    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    seeded: bool = False
    seed: int | None = None


# ── Tool Contract ──────────────────────────────────────────────────────────


class ToolRuntime(Protocol):
    """The tool surface a provider may call (wrapper over ``runtime.tools``)."""

    def list_available(self) -> list[str]: ...

    async def execute(self, name: str, /, **kwargs: Any) -> Any: ...

    def definition(self, name: str) -> Any: ...

    def build_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]: ...


# ── Teaching Contract ────────────────────────────────────────────────────────


class TeachingDecisionKind(str, Enum):
    """The kinds of pedagogical decision a Teaching Plugin produces."""

    EXPLAIN = "explain"
    SCAFFOLD = "scaffold"
    ASSESS = "assess"
    REMEDIATE = "remediate"
    PRACTICE = "practice"
    PROGRESS = "progress"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class TeachingInput:
    """What a Teaching Plugin needs to decide the next teaching step."""

    user_message: str
    learner_state: dict[str, Any]
    last_attempt: Any | None = None
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeachingDecision:
    """What Teaching Runtime decided should happen next — NOT how to run it."""

    kind: TeachingDecisionKind = TeachingDecisionKind.NOT_APPLICABLE
    strategy: str = ""
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class TeachingPlugin(Protocol):
    """Boundary between Agent Runtime and Teaching Runtime.

    A Teaching Plugin answers *"what should the teaching do next?"*.  It MUST
    NOT mutate runtime internals, drive the loop, bind a specific model, bypass
    the Tool Runtime, or spawn recursive execution.
    """

    name: str

    def decide(self, tin: TeachingInput) -> TeachingDecision: ...

    def scaffold(self, decision: TeachingDecision, context: RuntimeContext) -> str: ...

    def assess(self, decision: TeachingDecision, output: Any) -> dict[str, Any]: ...


# ── Trace Contract ──────────────────────────────────────────────────────────


@dataclass
class TraceEvent:
    """One observability / lineage record the provider MUST emit."""

    step: int
    kind: str  # model_call | tool_call | tool_result | decision | error | state | end
    data: dict[str, Any] = field(default_factory=dict)


# ── Output Contract ─────────────────────────────────────────────────────────


@dataclass
class TurnOutput:
    """What a completed (or stopped) turn returns."""

    final_text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    streamed_chars: int = 0
    events: list[Any] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


# ── Termination Contract ────────────────────────────────────────────────────


class TerminationReason(str, Enum):
    """How a turn ended."""

    COMPLETED = "completed"
    TOOL_LIMIT = "tool_limit"
    STEP_LIMIT = "step_limit"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class Termination:
    """Provider-agnostic description of why/how a turn ended."""

    reason: TerminationReason = TerminationReason.COMPLETED
    completed: bool = True
    detail: str = ""
    step_count: int = 0


# ── Error Contract ──────────────────────────────────────────────────────────


@dataclass
class TurnError:
    """Normalised error surface (never raw framework exceptions upstream)."""

    kind: str = ""  # model_error | tool_error | state_error | runtime_error | …
    message: str = ""
    recoverable: bool = False
    provider_detail: str = ""
    step: int = 0


# ── Top-level RuntimeProvider protocol ────────────────────────────────────


@dataclass
class ProviderRequest:
    """Composes all ten input-side contracts for one turn."""

    input: TurnInput
    state: TurnState
    context: RuntimeContext
    model: Model
    tools: ToolRuntime
    teaching: TeachingPlugin | None = None
    seed: int | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    """Composes all ten output-side contracts for one turn."""

    provider_id: str
    output: TurnOutput
    termination: Termination
    error: TurnError | None = None
    trace: list[TraceEvent] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


class RuntimeProvider(Protocol):
    """Every Agent Runtime Provider must implement ``run``.

    Provider can be replaced freely (Legacy / LangGraph / native) without
    touching Lumen business logic, Teaching Plugins, or the test system —
    they only ever see ``ProviderRequest`` / ``ProviderResult``.
    """

    provider_id: str

    async def run(self, request: ProviderRequest) -> ProviderResult: ...


__all__ = [
    "TurnInput",
    "TurnState",
    "RuntimeContext",
    "Model",
    "ModelSpec",
    "ToolRuntime",
    "TeachingDecisionKind",
    "TeachingInput",
    "TeachingDecision",
    "TeachingPlugin",
    "TraceEvent",
    "TurnOutput",
    "TerminationReason",
    "Termination",
    "TurnError",
    "ProviderRequest",
    "ProviderResult",
    "RuntimeProvider",
]

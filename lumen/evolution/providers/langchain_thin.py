"""P1 — LangGraph Thin Provider.

Official, **unmodified** LangGraph runtime + a deliberately thin Lumen adapter.

Structure::

    Lumen Provider Contract (ProviderRequest / ProviderResult)
            │   (thin translation — nothing re-implemented)
            ▼
    unmodified LangGraph StateGraph  (START → agent ⇄ tools → END)
            │
            ▼
    Lumen Model / ToolRuntime contract seams (framework-agnostic nodes)

Design intent — P1 is a *boundary*, not a second runtime.  Everything the
LangGraph runtime already provides is left to LangGraph:

* graph execution, state transition and the model→tool dispatch loop,
* run identity via ``config.thread_id`` and checkpoint idempotency,
* the loop safeguard via ``config.recursion_limit`` (native, not hand-rolled),
* durable checkpoint scoping to the thread.

The provider only maps the contract in/out:

* Lumen request  → initial LangGraph state (+ teaching seed, delivered as a
  *pre-turn hook*, never a graph node, mirroring production
  ``LOOP_CAPABILITIES``),
* Lumen Run / ``execution_generation`` → a LangGraph ``thread_id``,
* LangGraph stream events → canonical ``TraceEvent``,
* LangGraph termination / recursion trip → contract ``Termination``,
* budget / safety config → LangGraph ``recursion_limit``,
* Capability & Guarantee reporting via :meth:`LangGraphThinProvider.manifest`.

Boundary rules enforced here and asserted in ``tests/evolution/
test_langgraph_thin_provider.py``:

* Public API only — ``StateGraph`` / ``START`` / ``END`` / ``astream`` /
  ``compile`` / ``config.thread_id`` / ``config.recursion_limit``.  No
  ``langgraph._*`` internals, no fork, no patch, no re-implementation of
  scheduler / retry / checkpoint / resume / durability.
* LangGraph checkpoint = **Provider Execution State only** (messages, tool
  dispatch, run identity).  It is never Lumen domain / teaching / learner
  state — teaching decisions, learner state and policy live on the Lumen side
  of the bridge and are never stored on the graph.
* LangGraph-specific types never leak into Lumen domain — every node speaks the
  framework-agnostic ``Model`` / ``ToolRuntime`` contract seams.  Teaching
  semantics stay in Lumen; the Teaching Engine is **not** graphified.
* The provider is fixed within one ``execution_generation`` (a single LangGraph
  thread) and does **not** implement cross-provider checkpoint portability.

Graph API (``StateGraph``) rather than Functional API is the minimal reasonable
usage here: the harness drives every provider through the *same* framework-
agnostic ``Model`` contract, so ``create_react_agent`` (which mandates a
``langchain_core`` ``BaseChatModel``) would force LangChain types into the
harness and break the control-variable parity guarantee.  A small explicit
``StateGraph`` over the contract is the thin choice.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.errors import GraphInterrupt, GraphRecursionError
from langgraph.graph import END, START, StateGraph

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

MIN_RECURSION_FACTOR = 2
MIN_RECURSION_EXTRA = 2

# Provider Execution State schema version.  Providers are self-contained and the
# LangGraph checkpoint is *provider-private execution state* (never Lumen domain
# state), so a schema bump only ever invalidates old *thread* resumes — it is a
# safe, opaque evolution (see ``_safe_thread``).  Bump when ``AgentState`` or the
# node topology changes in a way that makes old checkpoints unreadable.
SCHEMA_VERSION = 1

# Semantic provider version — bumped when observable behaviour / guarantees
# change, independently of the execution-state schema.
PROVIDER_VERSION = "1.0.0"


class AgentState(TypedDict, total=False):
    """The ONLY state LangGraph holds for P1 — pure Provider Execution State.

    ``messages`` / ``tool_requests`` are the execution artifact of the loop;
    ``execution_generation`` is the Lumen Run identity mirrored onto the thread;
    ``schema_version`` pins the execution-state schema for version-safe resume.
    No teaching / learner / domain field is ever placed here.
    """

    messages: list[dict[str, Any]]
    tool_requests: list[tuple[str, dict[str, Any]]]
    execution_generation: str
    schema_version: int


@dataclass(frozen=True)
class _RunCtx:
    """Per-invocation runtime handles injected through the LangGraph config.

    Injected at ``run()`` time via ``config["configurable"]["__lumen"]`` so the
    compiled graph topology is static and reusable across turns (never rebuilt
    per run), while model/tools/seed differ per execution.  These handles are
    never written to checkpoint state — they do not leak into Persistence.
    """

    model: Any
    tools: Any
    seed: int | None


def _lctx(config: dict[str, Any]) -> _RunCtx:
    return config["configurable"]["__lumen"]


async def _agent_node(state: AgentState, config: dict[str, Any]) -> AgentState:
    """One LangGraph node: call the model; if it asks for tools, record them."""
    ctx = _lctx(config)
    messages = list(state.get("messages", []))
    out = await ctx.model.generate(messages, tools=ctx.tools.build_schemas(), seed=ctx.seed)
    calls = _tool_calls(out)
    if not calls:
        return {
            **state,
            "messages": messages + [{"role": "assistant", "content": _text(out)}],
            "tool_requests": [],
        }
    reqs: list[tuple[str, dict[str, Any]]] = [
        (str(c.get("name")), dict(c.get("args") or {})) for c in calls
    ]
    return {
        **state,
        "messages": messages + [{"role": "assistant", "content": _text(out)}],
        "tool_requests": reqs,
    }


async def _tools_node(state: AgentState, config: dict[str, Any]) -> AgentState:
    """One LangGraph node: dispatch every requested tool call exactly once."""
    ctx = _lctx(config)
    messages = list(state.get("messages", []))
    for step, (name, args) in enumerate(state.get("tool_requests", [])):
        try:
            content = str(await ctx.tools.execute(name, **args))
        except Exception as exc:  # noqa: BLE001
            content = f"Error: {exc}"
        # Canonical OpenAI tool-call message shape: real OpenAI-compatible
        # gateways reject the shorthand ``{"name", "args"}`` form (400
        # "No tool call found for function call output").  The assistant
        # message that precedes a ``role=tool`` message MUST carry the
        # tool_calls array in ``type/function/arguments`` form so the
        # provider can resolve the tool_call_id on the next model call.
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"t{step}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": f"t{step}", "content": content})
    return {**state, "messages": messages, "tool_requests": []}


def _route(state: AgentState) -> str:
    """Pure routing on state: LangGraph decides whether the turn continues."""
    return "tools" if state.get("tool_requests") else END


def _resolve_generation(request: ProviderRequest) -> str:
    """Map the Lumen Run / ``execution_generation`` onto a LangGraph thread.

    Priority: previously recorded ``execution_generation`` > ``turn_id`` > a
    fresh unique id.  The resolved value becomes the LangGraph ``thread_id``
    (the execution identity) and is persisted on the Lumen state snapshot.
    """
    state = request.state
    gen = state.snapshot.get("execution_generation") or state.turn_id or f"turn-{uuid4().hex[:12]}"
    if not state.turn_id:
        state.turn_id = str(gen)
    return str(gen)


class LangGraphThinProvider(RuntimeProvider):
    """Unmodified LangGraph runtime behind a thin Lumen contract adapter."""

    provider_id = "langgraph_thin"

    # ── Capability & Guarantee Manifest ─────────────────────────────────────
    # Declarative, runtime-free facts a caller / conformance test can assert.
    CAPABILITIES: dict[str, Any] = {
        "runtime": "unmodified-langgraph",
        "framework": "langgraph",
        "api_surface": [
            "StateGraph",
            "START",
            "END",
            "astream",
            "compile",
            "config.thread_id",
            "config.recursion_limit",
        ],
        # Provision P2 explicitly: these Runtime capabilities are NOT re-implemented
        # here — they are owned by the (unmodified) LangGraph runtime.
        "not_reimplemented": [
            "scheduler",
            "retry",
            "checkpointing",
            "resume",
            "durability",
            "recursion_limit",
        ],
        "langgraph_types_leak": "none",  # nodes speak Model / ToolRuntime contracts
        "teaching_model": "pre_turn_hook_not_graph_node",
        "checkpoint_scope": "provider_execution_state_only",
        "domain_state_vs_checkpoint": "separated",
        "cross_provider_checkpoint_portability": False,  # fixed in one execution_generation
        "functional_api": False,  # minimal reasonable usage = StateGraph over Model contract
    }

    GUARANTEES: dict[str, Any] = {
        "deterministic_replay": True,  # same request + seed → same output / side-effects
        "budget_integrity": True,  # step_budget honoured via native recursion_limit
        "state_integrity": True,  # each tool_request dispatched exactly once per run
        "interrupt": False,  # not exposed by the thin default graph
        "resume": True,  # caller-supplied execution_generation + checkpointer → continue
        "retry": True,  # a fresh execution_generation = an atomic, clean re-attempt
        "replay_by_thread": "requires checkpointer configured",
        "crash_recovery": "delegated to LangGraph checkpointer",
        # Operational / upgrade semantics (see module docstring + DoD).
        "retry_semantics": "atomic_attempt_new_execution_generation",
        "resume_semantics": "caller_supplied_generation_plus_checkpointer",
        "durability_semantics": "at_least_once_tool_dispatch_delegated_to_langgraph",
        "version_evolution": "schema_version_guard;_incompatible_thread_never_resumed",
    }

    def __init__(
        self,
        *,
        max_steps: int = 10,
        emit_trace: bool = True,
        checkpointer: Any = None,
    ) -> None:
        self._max_steps = max_steps
        self._emit_trace = emit_trace
        self._checkpointer = checkpointer
        # Compile ONCE: topology is static; model/tools/seed are injected per run
        # through the config, so the graph is reusable across turns and (with a
        # checkpointer) across resume/replay on the same thread.
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentState)
        # Node callables take (state, config): the documented LangGraph pattern
        # for per-invocation injection.  The published stubs only cover the
        # single-arg form, so the two-arg async nodes need a targeted ignore.
        builder.add_node("agent", _agent_node)  # type: ignore[arg-type]
        builder.add_node("tools", _tools_node)  # type: ignore[arg-type]
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
        builder.add_edge("tools", "agent")
        return builder.compile(checkpointer=self._checkpointer)

    # ── Capability & Guarantee reporting ───────────────────────────────────
    def manifest(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_version": PROVIDER_VERSION,
            "schema_version": SCHEMA_VERSION,
            "capabilities": {**self.CAPABILITIES, "schema_version": SCHEMA_VERSION},
            "guarantees": dict(self.GUARANTEES),
        }

    def version(self) -> dict[str, Any]:
        """Operational/diagnosability accessor: pinned semantic + schema version."""
        return {
            "provider_id": self.provider_id,
            "provider_version": PROVIDER_VERSION,
            "schema_version": SCHEMA_VERSION,
        }

    def _safe_thread(self, candidate: str, request: ProviderRequest) -> str:
        """Resolve the LangGraph thread for an execution with version safety.

        Default (no explicit ``config.resume``) honours the caller's
        ``execution_generation`` unchanged — every turn is an atomic attempt and
        retry is a *new* execution_generation.  Only an explicit ``resume=True``
        (with a checkpointer configured) continues a durable thread, and even
        then only when the persisted execution-state ``schema_version`` matches
        the current one.  An incompatible / unversioned thread is **never**
        silently resumed: a fresh generation is minted instead, and the reason is
        recorded on the Lumen snapshot so the guard is observable/auditable.

        This is a *guard on top of* the unmodified LangGraph runtime — it does not
        re-implement checkpoint/resume/durability, which remain owned by LangGraph.
        """
        if self._checkpointer is None or not request.config.get("resume"):
            if request.config.get("resume") and self._checkpointer is None:
                request.state.snapshot["resume_ignored"] = "no_checkpointer_configured"
            return candidate
        try:
            snap = self._graph.get_state({"configurable": {"thread_id": candidate}})
            persisted = (snap.values or {}) if snap is not None else {}
        except Exception:  # noqa: BLE001 — unreadable thread is treated as fresh
            persisted = {}
        if not persisted:
            return candidate  # fresh thread — safe to start
        stored = persisted.get("schema_version")
        if stored is not None and stored == SCHEMA_VERSION:
            return candidate  # compatible persisted thread; caller-requested resume
        fresh = f"turn-{uuid4().hex[:12]}"
        request.state.snapshot["version_guard"] = (
            f"thread_schema_version={stored!r} incompatible; refraining from resume; "
            f"fresh_thread={fresh}"
        )
        return fresh

    def _teaching_seed(self, request: ProviderRequest) -> str:
        from lumen.evolution.contract import TeachingInput

        teaching = request.teaching
        if teaching is None:
            return ""
        decision = teaching.decide(
            TeachingInput(user_message=request.input.user_message, learner_state={})
        )
        scaffold = teaching.scaffold(decision, request.context)
        return (
            f"You are teaching in mode={decision.kind.value}; strategy={decision.strategy}. "
            f"{scaffold}".strip()
        )

    async def run(self, request: ProviderRequest) -> ProviderResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": request.input.user_message}]
        messages = list(request.input.conversation_history) + messages
        system = self._teaching_seed(request) if request.teaching is not None else None
        messages.insert(0, {"role": "system", "content": system or "You are a helpful assistant."})

        # Execution identity: Lumen Run/execution_generation ↔ LangGraph thread.
        gen = self._safe_thread(_resolve_generation(request), request)
        request.state.snapshot["execution_generation"] = gen
        request.state.snapshot["checkpoint_scope"] = "provider_execution_state_only"

        # Budget / safety: we do NOT re-implement a loop counter.  The caller's
        # step budget is translated into LangGraph's native recursion_limit.
        step_budget = int(request.config.get("step_budget", self._max_steps))
        budget_requested = "step_budget" in request.config
        recursion_limit = request.config.get("recursion_limit") or (
            step_budget * MIN_RECURSION_FACTOR + MIN_RECURSION_EXTRA
        )

        config = {
            "recursion_limit": recursion_limit,
            "configurable": {
                "thread_id": gen,
                "__lumen": _RunCtx(request.model, request.tools, request.seed),
            },
        }

        trace: list[TraceEvent] = []
        steps = 0
        final_text = ""
        last_msgs: list[dict[str, Any]] = []
        error: TurnError | None = None
        reason = TerminationReason.COMPLETED
        detail = ""
        interrupted = False

        try:
            async for batch in self._graph.astream(
                {
                    "messages": messages,
                    "execution_generation": gen,
                    "schema_version": SCHEMA_VERSION,
                },
                config=config,
                stream_mode="updates",
            ):
                # An official LangGraph ``interrupt()`` surfaces as an ``__interrupt__``
                # stream update (a checkpointed human-in-the-loop pause), NOT an error.
                # We surface it as a contract interrupt and stop, leaving the graph
                # checkpointer to durably hold the resume state.
                if "__interrupt__" in batch:
                    interrupted = True
                    if self._emit_trace:
                        trace.append(
                            TraceEvent(
                                step=steps,
                                kind="interrupt",
                                data={"interrupts": [repr(i) for i in batch["__interrupt__"]]},
                            )
                        )
                    break
                for node_name, update in batch.items():
                    steps += 1
                    if self._emit_trace:
                        trace.append(TraceEvent(step=steps, kind="node", data={"node": node_name}))
                    if isinstance(update, dict):
                        update_msgs = update.get("messages")
                        if isinstance(update_msgs, list):
                            last_msgs = update_msgs
                        if node_name == "agent":
                            for m in reversed(update_msgs or []):
                                if (
                                    isinstance(m, dict)
                                    and m.get("role") == "assistant"
                                    and m.get("content")
                                ):
                                    final_text = str(m.get("content"))
                                    break
        except GraphInterrupt as exc:
            # Defensive fallback for subgraph-raised interrupts that bubble past the
            # root graph; still a checkpointed pause, never a runtime error.
            interrupted = True
            if self._emit_trace:
                trace.append(
                    TraceEvent(
                        step=steps,
                        kind="interrupt",
                        data={"interrupts": [repr(i) for i in getattr(exc, "args", ())]},
                    )
                )
        except GraphRecursionError:
            reason = (
                TerminationReason.BUDGET_EXHAUSTED
                if budget_requested
                else TerminationReason.STEP_LIMIT
            )
            detail = f"langgraph recursion_limit ({recursion_limit}) reached"
        except Exception as exc:  # noqa: BLE001
            reason = TerminationReason.ERROR
            detail = str(exc)
            error = TurnError(kind="runtime_error", message=str(exc), recoverable=False, step=steps)

        if interrupted:
            reason = TerminationReason.INTERRUPTED
            detail = "langgraph interrupt requested; checkpoint holds resume state"
            request.state.snapshot["interrupted"] = True

        tool_calls: list[tuple[str, dict[str, Any]]] = []
        for m in last_msgs:
            for tc in m.get("tool_calls", []):
                # Canonical OpenAI shape is now used by ``_tools_node``;
                # normalise both the shorthand and the canonical form.
                name = tc.get("name")
                args = tc.get("args")
                if name is None and isinstance(tc.get("function"), dict):
                    name = tc["function"].get("name")
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except (ValueError, TypeError):
                        args = {}
                if name is None:
                    continue
                tool_calls.append((str(name), dict(args or {})))

        return ProviderResult(
            provider_id=self.provider_id,
            output=TurnOutput(
                final_text=final_text,
                tool_calls=tool_calls,
                streamed_chars=len(final_text),
            ),
            termination=Termination(
                reason=reason,
                completed=reason == TerminationReason.COMPLETED,
                detail=detail,
                step_count=steps,
            ),
            error=error,
            trace=trace,
        )


__all__ = ["LangGraphThinProvider"]

"""Candidate 2 instrumentation tests — span shapes, metrics, no-op safety.

Verifies the instrumentation points added for execution-chain coverage:
LLM calls (agentic client seam), tool execution, retrieval, teaching
decisions, persistence, and turn-level metrics. Each test runs against a
no-op telemetry backend so failures here are real instrumentation bugs, not
backend I/O. Redaction is covered in ``test_redact.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from lumen.runtime.tool_protocol import BaseTool, ToolDefinition, ToolResult
from lumen.shared._util.observability import (
    NoopBackend,
    get_metrics,
    increment,
    observe,
    reset_metrics,
    sanitize_attrs,
    set_backend,
)
from lumen.shared._util.observability import (
    span as telemetry_span,
)


@pytest.fixture(autouse=True)
def _clean_telemetry():
    set_backend(NoopBackend())
    reset_metrics()
    yield
    set_backend(NoopBackend())
    reset_metrics()


# ── LLM instrumentation ────────────────────────────────────────────────────


def test_agentic_client_llm_seam_is_idempotent():
    """``_telemetry_instrumented`` wraps ``chat.completions.create`` once."""
    from unittest.mock import AsyncMock, MagicMock

    from lumen.runtime.agent_loop.engine.client import (
        LLMClientConfig,
        _telemetry_instrumented,
    )

    fake_usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    fake_response = MagicMock(usage=fake_usage)
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    config = LLMClientConfig(binding="test", model="gpt-4", api_key=None, base_url=None)
    wrapped = _telemetry_instrumented(fake_client, config)
    wrapped_again = _telemetry_instrumented(wrapped, config)

    assert wrapped_again is wrapped
    response = asyncio.run(wrapped.chat.completions.create(model="gpt-4"))
    assert response.usage.prompt_tokens == 10
    # Metrics recorded from the seam.
    snap = get_metrics().snapshot()
    assert snap.counters.get("llm.total", 0) >= 1


# ── Tool instrumentation ───────────────────────────────────────────────────


class _DummyTool(BaseTool):
    def __init__(self, name: str, success: bool = True) -> None:
        self._name = name
        self._success = success

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self._name, description="dummy")

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="ok", success=self._success)


def test_tool_execution_records_span_and_metrics():
    from lumen.runtime.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_DummyTool("dummy"))
    result = asyncio.run(registry.execute("dummy"))
    assert result.success is True
    snap = get_metrics().snapshot()
    assert snap.counters.get("tool.total", 0) >= 1


def test_tool_failure_records_error_metric():
    from lumen.runtime.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_DummyTool("failing", success=False))
    result = asyncio.run(registry.execute("failing"))
    assert result.success is False
    snap = get_metrics().snapshot()
    assert snap.counters.get("tool.errors", 0) >= 1


def test_tool_exception_propagates_and_counts_error():
    from lumen.runtime.tools.registry import ToolRegistry

    class _BoomTool(_DummyTool):
        async def execute(self, **kwargs) -> ToolResult:
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_BoomTool("boom"))
    with pytest.raises(RuntimeError):
        asyncio.run(registry.execute("boom"))
    snap = get_metrics().snapshot()
    assert snap.counters.get("tool.errors", 0) >= 1


# ── Retrieval instrumentation ──────────────────────────────────────────────


def test_retrieval_search_records_span():
    from lumen.shared.knowledge.rag.service import RAGService

    svc = RAGService(kb_base_dir="/tmp/lumen-obs-test", provider="simple")

    class _FakePipeline:
        async def search(self, query: str, kb_name: str, **kwargs):
            return {"content": "grounded answer text", "query": query}

    svc._resolve_provider = lambda kb_name: "simple"  # type: ignore[method-assign]
    svc._get_pipeline = lambda provider: _FakePipeline()  # type: ignore[method-assign]
    result = asyncio.run(svc.search("what is x?", "kb1"))
    assert result["provider"] == "simple"
    assert "x?" in result["query"]
    snap = get_metrics().snapshot()
    assert snap.counters.get("retrieval.total", 0) >= 1


# ── Teaching instrumentation ───────────────────────────────────────────────


def test_teaching_engine_decide_records_decision_attrs():
    from lumen.modes.learn.domain.teaching_graph import TeachingKnowledgeGraph
    from lumen.modes.learn.domain.teaching_models import (
        LearnerState,
        LearningGoal,
        TeachingEdge,
        TeachingKnowledgeModel,
        TeachingNode,
        TeachingNodeType,
        TeachingRelationType,
    )
    from lumen.modes.learn.policy.engine import TeachingEngine

    model = TeachingKnowledgeModel(
        nodes=[
            TeachingNode(id="n1", title="Node 1", type=TeachingNodeType.CONCEPT),
            TeachingNode(id="n2", title="Node 2", type=TeachingNodeType.CONCEPT),
        ],
        edges=[
            TeachingEdge(source="n1", target="n2", relation=TeachingRelationType.PREREQUISITE_OF),
        ],
    )
    graph = TeachingKnowledgeGraph(model)
    goal = LearningGoal(name="test", target_node_ids=["n2"])

    engine = TeachingEngine()
    action = engine.decide(graph=graph, goal=goal, learner=LearnerState())
    assert action is not None
    assert action.focus_node_id
    assert action.trace is not None
    snap = get_metrics().snapshot()
    assert snap.counters.get("teaching.total", 0) >= 1


# ── Persistence instrumentation ────────────────────────────────────────────


def test_persistence_wrappers_do_not_block(tmp_path):
    from lumen.runtime.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "obs.db")
    session = asyncio.run(store.create_session())
    turn = asyncio.run(store.create_turn(session["id"]))
    assert turn["id"]
    assert asyncio.run(store.update_turn_status(turn["id"], "completed")) is True
    assert asyncio.run(store.add_message(session["id"], "user", "hello")) is not None
    snap = get_metrics().snapshot()
    assert snap.counters.get("persistence.total", 0) >= 1


# ── Turn-level metrics ─────────────────────────────────────────────────────


def test_turn_metrics_counters():
    increment("turn.completed")
    increment("turn.failed")
    snap = get_metrics().snapshot()
    assert snap.counters["turn.completed"] >= 1
    assert snap.counters["turn.failed"] >= 1


# ── Redaction hardening ────────────────────────────────────────────────────


def test_span_attrs_redaction_hardening():
    out = sanitize_attrs({"api_key": "sk-abc123", "model": "gpt-4", "status": "ok"})
    assert out["api_key"] == "[REDACTED]"
    assert out["model"] == "gpt-4"
    assert out["status"] == "ok"


# ── No-op safety ───────────────────────────────────────────────────────────


def test_span_metrics_and_exception_behavior():
    with telemetry_span("happy", kind="test", metric="test"):
        pass
    with pytest.raises(ValueError):
        with telemetry_span("boom", kind="test", metric="test"):
            raise ValueError("expected")
    observe("test.latency", 0.5)
    increment("test.total")
    snap = get_metrics().snapshot()
    assert snap.counters.get("test.total", 0) >= 1
    assert snap.counters.get("test.errors", 0) >= 1
    assert "test.latency" in snap.histograms

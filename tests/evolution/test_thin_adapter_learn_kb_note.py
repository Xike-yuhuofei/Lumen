"""P1 (langgraph_thin) Learn turns must surface the attached knowledge bases.

Regression: under the production P1 provider the Learn system prompt is built
solely from the mastery scaffold (``_LearnTeachingPlugin.scaffold``). Unlike
the legacy pipeline it never injected the "attached knowledge bases" note, so
the tutor could not see that the goal's material already lived in a mounted KB
and wrongly asked the learner to upload it again (e.g. a file already imported
as ``种草-道层面的经验哲学.md``). These tests pin the KB note wiring.
"""

from __future__ import annotations

from typing import Any

import pytest

from lumen.runtime.agent_loop.capability import PromptBlock
from lumen.runtime.agent_loop.providers.langgraph_thin.plugin import _LearnTeachingPlugin
from lumen.runtime.context import UnifiedContext
from lumen.shared.knowledge.manifest import KbDocument, KbManifest


class _FakeCapability:
    """Minimal capability exposing a static mastery system block."""

    _BLOCK = "mastery tutor system block"

    def system_block(self, context: Any, *, language: str, prompts: dict) -> PromptBlock:
        return PromptBlock("mastery_tutor", self._BLOCK)


def _manifest(name: str, *documents: str) -> KbManifest:
    docs = tuple(KbDocument(name=doc, size=1024) for doc in documents)
    return KbManifest(
        name=name,
        provider="llamaindex",
        status="ready",
        total=len(docs),
        matched=len(docs),
        documents=docs,
    )


def _plugin(context: UnifiedContext, *, language: str = "zh") -> _LearnTeachingPlugin:
    return _LearnTeachingPlugin(
        context=context,
        language=language,
        capability=_FakeCapability(),
        prompts={},
    )


def _learn_context(*, knowledge_bases: list[str], language: str = "zh") -> UnifiedContext:
    context = UnifiedContext(
        session_id="s1",
        user_message="继续学习",
        knowledge_bases=knowledge_bases,
        language=language,
    )
    context.metadata["mastery_mode"] = True
    context.metadata["mastery_path_id"] = "g1"
    return context


def _stub_resolver(
    monkeypatch: pytest.MonkeyPatch, manifests: dict[str, KbManifest | None]
) -> list[str]:
    """Replace the access-checked resolver; record which KBs were asked for."""
    asked: list[str] = []

    def _resolve(kb_ref: str, **_kwargs: Any) -> KbManifest | None:
        asked.append(kb_ref)
        return manifests.get(kb_ref)

    monkeypatch.setattr("lumen.shared._util.user.resolve_kb_manifest", _resolve, raising=False)
    return asked


def test_scaffold_includes_mounted_kb_and_its_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(
        monkeypatch,
        {"种草": _manifest("种草", "种草-道层面的经验哲学.md")},
    )
    context = _learn_context(knowledge_bases=["种草"])

    out = _plugin(context).scaffold(None, None)

    # The tutor is told the KB is attached, that rag needs its exact name, and
    # what the KB actually contains — so it never asks the learner to upload
    # material that is already imported.
    assert "用户已挂载知识库：种草" in out
    assert "调用 rag 时" in out
    assert "种草-道层面的经验哲学.md" in out


def test_scaffold_without_kb_yields_no_note(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _stub_resolver(monkeypatch, {})
    context = _learn_context(knowledge_bases=[])

    out = _plugin(context).scaffold(None, None)

    assert asked == []
    assert "知识库" not in out
    assert _FakeCapability._BLOCK in out


def test_scaffold_inaccessible_kb_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolver(monkeypatch, {"course": _manifest("course", "a.pdf"), "secret": None})
    context = _learn_context(knowledge_bases=["course", "secret"])

    out = _plugin(context).scaffold(None, None)

    # Both names ride in the rag note (both are attached), but the manifest
    # line is only rendered for the KB that actually resolved.
    assert "course" in out and "secret" in out
    assert "course（llamaindex" in out
    assert "secret（" not in out


def test_scaffold_unreadable_kb_does_not_fail_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(kb_ref: str, **_kwargs: Any) -> KbManifest:
        raise OSError("permission denied")

    monkeypatch.setattr("lumen.shared._util.user.resolve_kb_manifest", _boom, raising=False)
    context = _learn_context(knowledge_bases=["broken"])

    out = _plugin(context).scaffold(None, None)

    # The rag note still lands (KB name known); only the manifest line is lost.
    assert "用户已挂载知识库：broken" in out
    assert _FakeCapability._BLOCK in out

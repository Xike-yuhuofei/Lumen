"""Facade request-resolution decoupling from the legacy CapabilityRegistry.

Since Phase 5/6A the only canonical Learn id is ``mode.learn``.  The App
facade must resolve Learn requests without consulting ``CapabilityRegistry``
manifests, while keeping ``mastery_path`` / ``mastery`` compatible and generic
``chat`` behavior unchanged (the pre-requisite for later deleting
``MasteryPathCapability``).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.app import DeepTutorApp, TurnRequest


def _broken_registry():
    """A CapabilityRegistry stand-in that fails any manifest access.

    Proves the facade never needs ``get_manifests()`` to resolve a request.
    """

    class BrokenRegistry:
        def get_manifests(self):  # pragma: no cover - must not be called
            raise AssertionError("resolve_capability must not read manifests")

        def list_capabilities(self):  # pragma: no cover
            raise AssertionError("resolve_capability must not list capabilities")

    return BrokenRegistry()


def test_learn_names_resolve_to_canonical_mode_learn():
    app = DeepTutorApp()
    app.capabilities = _broken_registry()  # type: ignore[assignment]

    assert app.resolve_capability("mode.learn") == "mode.learn"
    assert app.resolve_capability("mastery_path") == "mode.learn"
    assert app.resolve_capability("mastery") == "mode.learn"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("chat", "chat"),
        ("", "chat"),
        (None, "chat"),
    ],
)
def test_generic_chat_resolution_unaffected(value, expected):
    app = DeepTutorApp()
    assert app.resolve_capability(value) == expected


@pytest.mark.parametrize("value", ["auto", "quiz", "foo"])
def test_unknown_capabilities_rejected(value):
    app = DeepTutorApp()
    with pytest.raises(ValueError, match="Unknown capability"):
        app.resolve_capability(value)


def test_get_capability_availability_exposes_canonical_name():
    app = DeepTutorApp()
    app.capabilities = _broken_registry()  # type: ignore[assignment]

    assert app.get_capability_availability("mastery_path").name == "mode.learn"
    assert app.get_capability_availability("mastery").name == "mode.learn"
    assert app.get_capability_availability("mode.learn").name == "mode.learn"
    assert app.get_capability_availability("chat").name == "chat"


def test_get_capability_contract_learn_returns_canonical_snapshot():
    app = DeepTutorApp()

    contract = app.get_capability_contract("mastery")
    assert contract["name"] == "mode.learn"
    assert contract["availability"]["name"] == "mode.learn"

    chat = app.get_capability_contract("chat")
    assert chat["name"] == "chat"


def test_start_turn_hands_canonical_mode_learn_to_runtime(monkeypatch):
    """A Learn request from the facade reaches the runtime as ``mode.learn``
    without flowing through the legacy MasteryPathCapability path."""
    app = DeepTutorApp()
    app.capabilities = _broken_registry()  # type: ignore[assignment]

    captured: dict[str, Any] = {}

    async def fake_start_turn(payload: dict[str, Any]):
        captured["capability"] = payload["capability"]
        return {"id": "session-1"}, {"id": "turn-1"}

    async def fake_update_session_preferences(_sid: str, _prefs: dict[str, Any]):
        return None

    app.runtime.start_turn = fake_start_turn  # type: ignore[method-assign]
    app.store.update_session_preferences = (  # type: ignore[method-assign]
        fake_update_session_preferences
    )

    _session, _turn = asyncio.run(
        app.start_turn(TurnRequest(content="linear algebra", capability="mastery_path"))
    )
    assert captured["capability"] == "mode.learn"

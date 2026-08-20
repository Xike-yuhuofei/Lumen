"""Regression tests for Gitee AI 503 ``no_available_account`` handling.

Root cause: ``OpenAICompatProvider.chat()`` flattens the SDK ``InternalServerError``
into a text-only ``LLMResponse``, dropping the HTTP status code. The provider-level
transient detector then matched only substrings and the Gitee body
(``type: server_error`` / ``code: no_available_account``, no literal ``503``) failed
every marker — so the error was misclassified as **non-transient** and never retried,
surfacing the raw upstream 503 to the user.

These tests pin the fix: the flattened Gitee body must be classified as transient
(so the existing bounded retry budget applies) and, if the retry budget is exhausted,
must map to an actionable 503 with a clean message.
"""

from __future__ import annotations

from typing import Any

import pytest

from lumen.shared._util.llm.error_mapping import map_error
from lumen.shared._util.llm.exceptions import LLMAPIError
from lumen.shared._util.llm.provider_core.base import LLMProvider, LLMResponse

GITEE_NO_ACCOUNT_BODY = (
    "Error: {'error': {'code': 'no_available_account', "
    "'message': 'no available account', 'type': 'server_error'}}"
)


class _ScriptedChatProvider(LLMProvider):
    """Single failing response, then an actual answer."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return self._responses.pop(0)

    async def chat_stream(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "Qwen3-8B"


def _error_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, finish_reason="error")


def test_no_available_account_flat_body_is_transient() -> None:
    """The flattened Gitee body must be treated as a transient upstream failure."""
    assert LLMProvider._is_transient_error(GITEE_NO_ACCOUNT_BODY)

    # A narrowed-body variant (only the code, no ``503`` literal) must also be
    # recognised, since the status code is not present in the flattened content.
    assert LLMProvider._is_transient_error("no_available_account")
    assert LLMProvider._is_transient_error("no available account")


@pytest.mark.asyncio
async def test_no_available_account_is_retried_until_success() -> None:
    """A transient no-available-account failure must be retried, not returned raw."""
    provider = _ScriptedChatProvider(
        [
            _error_response(GITEE_NO_ACCOUNT_BODY),
            _error_response(GITEE_NO_ACCOUNT_BODY),
            LLMResponse(content="a valid answer", finish_reason="stop"),
        ]
    )

    resp = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        model="Qwen3-8B",
        retry_delays=(0.01, 0.01),
    )

    assert provider.calls == 3
    assert resp.finish_reason == "stop"
    assert resp.content == "a valid answer"


@pytest.mark.asyncio
async def test_no_available_account_surfaces_friendly_503_when_exhausted() -> None:
    """When the bounded retry budget runs out the error must stay explicit and clean."""
    provider = _ScriptedChatProvider([_error_response(GITEE_NO_ACCOUNT_BODY)])

    resp = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}], model="Qwen3-8B", retry_delays=()
    )

    assert resp.finish_reason == "error"
    assert provider.calls == 1

    mapped = map_error(RuntimeError(resp.content or ""), provider="gitee")
    assert isinstance(mapped, LLMAPIError)
    assert mapped.status_code == 503
    assert "gitee" in str(mapped)
    # Never leak the raw upstream JSON as the only user-facing feedback.
    assert "no_available_account" not in str(mapped)
    assert "{" not in str(mapped)


def test_map_error_no_available_account_direct() -> None:
    """map_error() with a raw no-available-account body yields a clean 503."""
    mapped = map_error(RuntimeError(GITEE_NO_ACCOUNT_BODY), provider="gitee")
    assert isinstance(mapped, LLMAPIError)
    assert mapped.status_code == 503
    assert "gitee" in str(mapped)
    assert "no_available_account" not in str(mapped)
    assert "{" not in str(mapped)

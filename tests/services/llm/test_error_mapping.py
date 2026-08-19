"""Tests for LLM error mapping helpers."""

from lumen.shared._util.llm.error_mapping import map_error
from lumen.shared._util.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMRateLimitError,
    ProviderContextWindowError,
)


class DummyError(Exception):
    """Custom error used for mapping tests."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_map_error_status_code_auth() -> None:
    """401 errors should map to authentication failures."""
    mapped = map_error(DummyError("auth failed", status_code=401), provider="openai")
    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_status_code_rate_limit() -> None:
    """429 errors should map to rate limit failures."""
    mapped = map_error(DummyError("rate limited", status_code=429), provider="openai")
    assert isinstance(mapped, LLMRateLimitError)


def test_map_error_message_context_window() -> None:
    """Context length errors should map to the provider context window error."""
    mapped = map_error(DummyError("maximum context length exceeded"), provider="openai")
    assert isinstance(mapped, ProviderContextWindowError)


def test_map_error_falls_back_to_api_error() -> None:
    """Unknown errors should fall back to generic API error mapping."""
    mapped = map_error(DummyError("boom", status_code=500), provider="openai")
    assert isinstance(mapped, LLMAPIError)
    assert mapped.status_code == 500


def test_map_error_token_expired_clean_message() -> None:
    """An expired upstream token must yield an actionable message, not raw JSON."""
    mapped = map_error(
        DummyError('OpenAI API error: {"error":{"code":"token_expired","message":"token has expired"}}', status_code=401),
        provider="gitee",
    )
    assert isinstance(mapped, LLMAuthenticationError)
    assert mapped.status_code == 401
    assert "已过期" in str(mapped)
    assert "GITEE_API_KEY" in str(mapped)
    # Raw provider body must never be the user-facing message.
    assert "token_expired" not in str(mapped)
    assert "{" not in str(mapped)


def test_map_error_invalid_key_clean_message() -> None:
    """An invalid/missing key must map to a clear auth failure without raw JSON."""
    mapped = map_error(
        DummyError('OpenAI stream error: {"error":"Invalid API key"}', status_code=401),
        provider="zhipu",
    )
    assert isinstance(mapped, LLMAuthenticationError)
    assert "无效" in str(mapped)
    assert "ZHIPU_API_KEY" in str(mapped)
    assert "{" not in str(mapped)

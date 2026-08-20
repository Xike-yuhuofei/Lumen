from __future__ import annotations

from lumen.shared._util.llm.request_compat import (
    error_text,
    is_image_input_unsupported,
    is_stream_options_unsupported,
    is_tool_schema_unsupported,
    is_transient_provider_error,
)


class _Response:
    text = "Unsupported parameter: stream_options"


class _ProviderError(Exception):
    response = _Response()


def test_error_text_prefers_provider_response_body() -> None:
    assert error_text(_ProviderError("generic message")) == (
        "unsupported parameter: stream_options"
    )


def test_request_compatibility_classifiers_match_known_provider_errors() -> None:
    assert is_stream_options_unsupported(ValueError("unknown parameter: stream_options"))
    assert is_tool_schema_unsupported(ValueError("function_declaration is unsupported"))
    assert is_image_input_unsupported(ValueError("content must be a string"))


def test_request_compatibility_classifiers_ignore_unrelated_errors() -> None:
    error = RuntimeError("rate limit exceeded")

    assert not is_stream_options_unsupported(error)
    assert not is_tool_schema_unsupported(error)
    assert not is_image_input_unsupported(error)


def test_is_transient_provider_error_matches_gitee_503() -> None:
    """Gitee 503 ``no_available_account`` must be flagged transient for retry."""
    gitee_body = (
        "{'error': {'code': 'no_available_account', "
        "'message': 'no available account', 'type': 'server_error'}}"
    )

    class _SDK503(Exception):
        status_code = 503
        body = gitee_body

        def __init__(self) -> None:
            super().__init__(f"Error code: 503 - {gitee_body}")

    assert is_transient_provider_error(_SDK503())


def test_is_transient_provider_error_matches_flat_body() -> None:
    """The flattened body (status dropped by generic error shims) still matches."""
    assert is_transient_provider_error(ValueError("no_available_account"))
    assert is_transient_provider_error(ValueError("server_error"))


def test_is_transient_provider_error_ignores_client_errors() -> None:
    """Non-transient 4xx / unrelated errors must never be retried as transient."""
    class _SDK400(Exception):
        status_code = 400
        body = "{'error': {'code': 'bad request', 'message': 'bad'}}"

        def __init__(self) -> None:
            super().__init__("HTTP 400")

    assert not is_transient_provider_error(_SDK400())
    assert not is_transient_provider_error(ValueError("rate limit exceeded"))

"""Provider-error classifiers used by retry and graceful-degradation paths."""

from __future__ import annotations


def error_text(exc: Exception) -> str:
    """Return the best available lowercase provider error body."""
    response = getattr(exc, "response", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
        or getattr(exc, "message", None)
        or str(exc)
    )
    return str(body).lower()


def is_stream_options_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected OpenAI's ``stream_options`` parameter."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "stream_options",
            "stream options",
            "unknown parameter",
            "unrecognized request argument",
            "unsupported parameter",
            "extra inputs are not permitted",
            "unexpected keyword",
        )
    )


def is_tool_schema_unsupported(exc: Exception) -> bool:
    """Whether a provider rejected native tool/function-calling schemas."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "tool",
            "function_declaration",
            "function declaration",
            "function_declarations",
            "tool_choice",
            "parameters.properties",
            "404_not_found",
            "404 not_found",
        )
    )


def is_image_input_unsupported(exc: Exception) -> bool:
    """Whether a provider or model rejected multimodal message content."""
    text = error_text(exc)
    return any(
        marker in text
        for marker in (
            "image",
            "vision",
            "multimodal",
            "image_url",
            "content type",
            "must be a string",
            "expected a string",
            "expected string",
            "invalid type for 'messages",
        )
    )


def is_transient_provider_error(exc: Exception) -> bool:
    """Whether a provider error is a transient upstream outage worth retrying.

    Detection is intentionally cheap and subclass-independent so it works for
    both the OpenAI SDK exceptions and their flattened message forms:

    * an explicit HTTP 503 status, and/or
    * a body marking an account-pool / serving outage (Gitee AI returns
      ``503`` + ``code: no_available_account`` + ``type: server_error``).

    Only the singular status is honoured (not a blanket ``5xx``), because a
    provider ``4xx`` should never be retried here.
    """
    if getattr(exc, "status_code", None) == 503:
        return True
    # The anthropic SDK reports status differently; fall through to the body.
    text = error_text(exc)
    status = getattr(exc, "status_code", None)
    if status is None:
        try:
            status = int(getattr(exc, "status", None) or 0) or None
        except (TypeError, ValueError):
            status = None
    if status == 503:
        return True
    return any(
        marker in text
        for marker in (
            # Gitee AI account-pool outage.
            "no_available_account",
            "no available account",
            "server_error",
            # Generic transient overload / unavailable phrasings that lack a
            # numeric status but are still safely retryable.
            "temporarily unavailable",
            "overloaded",
            "try again later",
        )
    )


__all__ = [
    "error_text",
    "is_image_input_unsupported",
    "is_stream_options_unsupported",
    "is_tool_schema_unsupported",
    "is_transient_provider_error",
]

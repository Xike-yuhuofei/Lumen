"""Redaction tests — telemetry records must never leak secrets."""

from __future__ import annotations

from lumen.shared._util.observability import REDACTED, sanitize_attrs, sanitize_text


def test_masks_sensitive_attribute_values():
    out = sanitize_attrs(
        {
            "api_key": "sk-abc123def456ghi789",
            "model": "gpt-4",
            "prompt": "hello",
        }
    )
    assert out["api_key"] == REDACTED
    assert out["model"] == "gpt-4"
    assert out["prompt"] == "hello"


def test_masks_nested_and_header_values():
    out = sanitize_attrs(
        {
            "headers": {"Authorization": "Bearer abcdef0123456789", "Content-Type": "json"},
            "meta": {"token": "t-12345"},
        }
    )
    assert out["headers"]["Authorization"] == REDACTED
    assert out["headers"]["Content-Type"] == "json"
    assert out["meta"]["token"] == REDACTED


def test_masks_list_items():
    out = sanitize_attrs({"tags": ["a", "sk-abcdefghijklmnop", "b"]})
    assert out["tags"][1] == REDACTED
    assert out["tags"][0] == "a"


def test_sanitize_text_masks_embedded_secrets():
    text = sanitize_text("use api key sk-abcdefghijklmnop now")
    assert "sk-abcdefghijklmnop" not in text
    assert REDACTED in text

    bearer = sanitize_text("Authorization: Bearer xyz.abc.def-ghijklmno")
    assert "xyz.abc.def-ghijklmno" not in bearer


def test_sanitize_text_allows_plain_content():
    assert sanitize_text("plain message") == "plain message"


def test_sanitize_attrs_handles_none():
    assert sanitize_attrs(None) == {}

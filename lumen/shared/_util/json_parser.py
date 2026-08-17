#!/usr/bin/env python
"""
Robust JSON parsing utilities with automatic repair and markdown extraction.

Owned by ``lumen`` (single real implementation). ``deeptutor.utils.json_parser``
re-exports this module for existing importers only.
"""

import json
import logging
import re
from typing import Any

_repair_json_fn: Any = None

try:
    from json_repair import repair_json as _repair_json_import
except ImportError:
    pass
else:
    _repair_json_fn = _repair_json_import

# Keep a public alias so tests and callers can patch the repair hook directly.
repair_json = _repair_json_fn

logger = logging.getLogger(__name__)

_UNSET = object()


def _decode_longest_json_value(text: str) -> Any:
    """Return the longest top-level JSON value decodable from *text*.

    LLM responses may surround the payload with prose on either side, and that
    prose can itself contain small valid JSON fragments (e.g. schema examples
    in a reasoning prelude — issues #673/#692). Decoding every candidate and
    keeping the longest one picks the actual payload over such fragments.
    Returns ``_UNSET`` when nothing decodes.
    """
    decoder = json.JSONDecoder()
    best: Any = _UNSET
    best_length = 0
    pos = 0
    while True:
        starts = [i for i in (text.find("{", pos), text.find("[", pos)) if i != -1]
        if not starts:
            return best
        start = min(starts)
        try:
            parsed, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as err:
            # Resume past the failure point: an opener inside the failed span
            # could only yield a fragment of it, and repair handles those.
            pos = start + max(1, err.pos)
            continue
        except RecursionError:
            return best
        if consumed > best_length:
            best, best_length = parsed, consumed
        pos = start + consumed


def parse_json_response(
    response: str,
    logger_instance: Any = None,
    fallback: Any = _UNSET,
) -> Any:
    """Safely parse JSON from LLM responses with automatic repair."""
    log = logger_instance or logger

    if fallback is _UNSET:
        fallback = {}

    if not response or not response.strip():
        log.warning("LLM returned empty response")
        return fallback

    try:
        return json.loads(response)
    except (json.JSONDecodeError, TypeError) as parse_error:
        log.debug(f"Complete response JSON parse failed: {parse_error}")

    extracted_response = response
    if "```" in response:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", response, re.DOTALL)
        if json_match:
            extracted_response = json_match.group(1).strip()
            log.debug("Extracted JSON from markdown code block")

    try:
        return json.loads(extracted_response)
    except (json.JSONDecodeError, TypeError) as parse_error:
        log.debug(f"Direct JSON parse failed: {parse_error}")

    if "<think" in extracted_response.lower():
        cleaned = re.sub(
            r"<think\b[^>]*>.*? response",
            "",
            extracted_response,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*<think\b[^>]*>.*?(?=[{\[])",
            "",
            cleaned,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = cleaned.strip()
        if cleaned != extracted_response.strip():
            if not cleaned:
                log.warning("LLM response contained only thinking reasoning, no JSON payload")
                return fallback
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, TypeError):
                extracted_response = cleaned

    if isinstance(extracted_response, str):
        decoded = _decode_longest_json_value(extracted_response)
        if decoded is not _UNSET:
            return decoded

    if repair_json is None:
        log.warning("json-repair library not installed, cannot repair malformed JSON")
        log.debug(f"Response: {extracted_response[:200]}")
        return fallback

    try:
        log.debug("Attempting JSON repair")
        repaired = repair_json(extracted_response)
        result = json.loads(repaired)
        log.info("Successfully repaired malformed JSON")
        return result
    except Exception as repair_error:
        log.debug(f"JSON repair failed: {repair_error}")
        log.debug(f"Response: {extracted_response[:200]}")
        return fallback


def safe_json_loads(data: str, fallback: Any = _UNSET) -> Any:
    """Simple wrapper for safe JSON loading."""
    if fallback is _UNSET:
        fallback = {}
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"JSON parse error: {e}")
        return fallback


__all__ = ["parse_json_response", "repair_json", "safe_json_loads"]

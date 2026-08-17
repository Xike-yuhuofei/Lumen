#!/usr/bin/env python
"""Compatibility facade — real implementation now in ``lumen.shared._util.json_parser``."""
from __future__ import annotations

from lumen.shared._util.json_parser import (  # noqa: F401
    _decode_longest_json_value,
    parse_json_response,
    repair_json,
    safe_json_loads,
)

__all__ = ["parse_json_response", "repair_json", "safe_json_loads", "_decode_longest_json_value"]
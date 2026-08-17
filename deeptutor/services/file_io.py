#!/usr/bin/env python
"""Compatibility facade — real implementation now in ``lumen.shared._util.file_io``."""

from __future__ import annotations

from lumen.shared._util.file_io import atomic_write_json, atomic_write_text  # noqa: F401

__all__ = ["atomic_write_json", "atomic_write_text"]

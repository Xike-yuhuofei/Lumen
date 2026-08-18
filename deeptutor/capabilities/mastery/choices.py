"""Deprecated compatibility facade — see ``lumen.modes.learn.assessment.choices``.

The choice-question data contract is owned by ``lumen/modes/learn/assessment``.
This module re-exports it for existing importers and tests only.
"""
from __future__ import annotations

from lumen.modes.learn.assessment.choices import *  # noqa: F401,F403
from lumen.modes.learn.assessment.choices import __all__  # noqa: F401

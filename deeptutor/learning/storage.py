"""Deprecated compatibility facade — see ``lumen.modes.learn.adapters.storage``.

The Learner Domain State store (``LearningStore``) is owned by
``lumen/modes/learn/`` since Phase 6B1.  This module re-exports it for existing
importers and tests only.
"""
from lumen.modes.learn.adapters.storage import *  # noqa: F401,F403
from lumen.modes.learn.adapters.storage import _atomic_write_text  # noqa: F401

__all__ = ["LearningStore", "_atomic_write_text"]  # noqa: F405

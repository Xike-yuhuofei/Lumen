"""Deprecated compatibility facade — see ``lumen.modes.learn.application.prompts``.

The prompt YAML files are owned by ``lumen/modes/learn/prompts/`` since
Phase 6B1; this module only re-exports the loader for existing importers.
"""

from lumen.modes.learn.application.prompts import *  # noqa: F401,F403

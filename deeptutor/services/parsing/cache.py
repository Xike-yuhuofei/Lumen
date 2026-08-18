"""Deprecated compatibility facade — see ``lumen.shared.knowledge.parsing.cache``."""

from lumen.shared.knowledge.parsing.cache import *  # noqa: F401,F403

__all__ = [  # noqa: F405
    "MANIFEST_FILENAME",
    "cleanup_failed",
    "find_content_dir",
    "is_ready",
    "load_ir",
    "lookup",
    "reserve",
    "signature_dir",
    "source_hash_from_path",
    "write_manifest",
]

"""Knowledge-base kind discriminators.

A KB entry's ``type`` field tells the rest of the system how to treat it.
Most KBs are the default *indexed* kind (chunk → embed → retrieve via an RAG
provider) and carry no ``type``. *Connected* KBs are pointers: their content
lives outside ``data/knowledge_bases`` and we never copy or re-index it. These
flavours exist today:

* ``linked`` — a pointer (``external_path``) to a folder that already holds an
  engine index the user built elsewhere. Retrieval reads that index in place —
  the indexing step is skipped, and the KB is queried by its bound
  ``rag_provider`` exactly like an ordinary KB.
All connected flavours share the same lifecycle quirks: no on-disk folder under
``base_dir``, no embedding reconcile, and deletion must never touch the
external resource. The :func:`is_connected_kb` / :func:`external_root_of` helpers
let the manager treat them uniformly without sprinkling ``type`` literals
across the codebase.

Kept in its own low-level module so both :mod:`deeptutor.knowledge.manager`
and the capability layer can import it without a cycle.
"""

from __future__ import annotations

from typing import Any

# A linked engine index: a pointer (``external_path``) to a folder that already
# contains a self-contained index built by one of our local providers. We mount
# it in place and retrieve via the bound provider — no copy, no re-index.
LINKED_KB_TYPE = "linked"

# Every pointer/connected KB type. Membership here is what makes the manager
# skip the index pipeline, the orphan prune and the embedding reconcile.
CONNECTED_KB_TYPES = frozenset(
    {
        LINKED_KB_TYPE,
    }
)


def is_connected_kb(entry: Any) -> bool:
    """True for pointer KBs whose data lives outside ``data/knowledge_bases``."""
    return isinstance(entry, dict) and entry.get("type") in CONNECTED_KB_TYPES


def supports_local_raw_files(entry: Any) -> bool:
    """Whether the KB owns a DeepTutor-managed local ``raw/`` directory.

    Connected KBs are pointers to external resources.  Some point at a local
    folder and others at a remote service, but neither kind participates in
    DeepTutor's raw-file upload and management API.
    """
    return isinstance(entry, dict) and not is_connected_kb(entry)


def external_root_of(entry: Any) -> str | None:
    """Absolute path a connected KB points at, or ``None`` for ordinary KBs.

    ``linked`` KBs store it under ``external_path``. One accessor so callers
    don't care which.
    """
    if not isinstance(entry, dict):
        return None
    return entry.get("external_path")


__all__ = [
    "LINKED_KB_TYPE",
    "CONNECTED_KB_TYPES",
    "is_connected_kb",
    "supports_local_raw_files",
    "external_root_of",
]

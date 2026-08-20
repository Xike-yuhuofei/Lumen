"""Constants shared across the Learner Domain commit foundation."""

from __future__ import annotations

# Bump when the serialised ``state_json`` aggregate shape changes.
STATE_SCHEMA_VERSION = 1

# Evidence schema version stamped on every row; bump on schema evolution and
# re-import rather than rewriting historical rows.
EVIDENCE_SCHEMA_VERSION = 1

__all__ = ["STATE_SCHEMA_VERSION", "EVIDENCE_SCHEMA_VERSION"]
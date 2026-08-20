"""Pluggable storage backends for chat-session artifacts.

Currently exposes only :mod:`attachment_store`, which persists user-uploaded
chat attachments to disk so the frontend can preview them after the original
base64 payload is dropped from the message record.

Canonical home: ``lumen/shared/_util/storage`` (migrated from
``lumen/services/storage``).
"""

from __future__ import annotations

from lumen.shared._util.storage.attachment_store import (
    AttachmentStore,
    LocalDiskAttachmentStore,
    get_attachment_store,
    reset_attachment_store,
)

__all__ = [
    "AttachmentStore",
    "LocalDiskAttachmentStore",
    "get_attachment_store",
    "reset_attachment_store",
]

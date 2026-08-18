# ruff: noqa: F405
"""Document text extraction — canonical implementation lives in ``lumen``."""

from __future__ import annotations

from lumen.shared._util.document_extractor import *  # noqa: F401,F403

__all__ = [
    "SUPPORTED_DOC_EXTENSIONS",
    "MAX_DOC_BYTES",
    "MAX_TOTAL_DOC_BYTES",
    "MAX_EXTRACTED_CHARS_PER_DOC",
    "MAX_EXTRACTED_CHARS_TOTAL",
    "DocumentExtractionError",
    "UnsupportedDocumentError",
    "CorruptDocumentError",
    "EmptyDocumentError",
    "DocumentTooLargeError",
    "is_document_extension",
    "extract_text_from_bytes",
    "extract_text_from_path",
    "extract_documents_from_records",
]

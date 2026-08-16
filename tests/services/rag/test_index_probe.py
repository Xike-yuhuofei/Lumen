from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.rag.index_probe import (
    has_ready_provider_index,
    inspect_kb_versions,
    inspect_provider_index,
    inspect_provider_version,
    provider_failure_summary,
)


def _write_meta(version_dir: Path, *, provider: str, signature: str | None = None) -> None:
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "version": version_dir.name,
                "provider": provider,
                "signature": signature or provider,
                "layout": "flat",
            }
        ),
        encoding="utf-8",
    )


def test_llamaindex_requires_real_storage_files(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )

    probe = inspect_provider_index("llamaindex", version_dir)

    assert probe.ready is False
    assert "index_store.json" in probe.failure_summary
    assert probe.doc_count == 1

    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    probe = inspect_provider_index("llamaindex", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_kb_versions_overrule_fake_llamaindex_ready_marker(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    _write_meta(version_dir, provider="llamaindex", signature="sig")

    versions = inspect_kb_versions(tmp_path, "llamaindex")

    assert versions[0]["ready"] is False
    assert "index_store.json" in versions[0]["failure_summary"]
    assert has_ready_provider_index(tmp_path, "llamaindex") is False
    assert "index_store.json" in provider_failure_summary(tmp_path, "llamaindex")


def test_legacy_provider_collapses_to_llamaindex(tmp_path: Path) -> None:
    """A removed-engine version entry is inspected as LlamaIndex storage."""
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="legacy")

    probe = inspect_provider_index("legacy", version_dir)

    # Unknown providers collapse to the default LlamaIndex inspection.
    assert probe.provider == "llamaindex"
    assert probe.ready is False


def test_provider_mismatch_is_not_ready(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="legacy")
    entry = {
        "provider": "legacy",
        "signature": "legacy",
        "ready": True,
        "storage_path": str(version_dir),
    }

    probe = inspect_provider_version(entry, "llamaindex")

    assert probe.ready is False
    assert probe.diagnostics["provider_mismatch"] is True

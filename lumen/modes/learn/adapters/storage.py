from __future__ import annotations

from pathlib import Path
import threading
import time
import uuid as _uuid

from lumen.modes.learn.domain.models import LearningProgress
from lumen.shared._util.file_io import atomic_write_text as _atomic_write_text
from lumen.shared._util.runtime_paths import get_path_service

# Public facade contract preserved for callers and tests: this module still
# exposes ``LearningStore`` and ``_atomic_write_text``. The provider is now the
# Learner-Domain SQLite authority (:mod:`lumen.modes.learn.commit`) — every
# authoritative write funnels through an idempotent, CAS-guarded DomainCommit;
# there is no JSON ``save()`` bypass. Legacy JSON is migrated once on
# first use and thereafter only exists as a read-only backup (never dual-written).
#
# The repository is initialised *lazily* from ``self._root``/``self._db_path`` so
# the store works whether constructed through its own ``__init__`` or through a
# test override that only sets ``_root``.
__all__ = ["LearningStore", "_atomic_write_text"]


class LearningStore:
    """Commit-backed, SQLite-authoritative store for ``LearningProgress``.

    The public ``save / load / exists / delete / list_all`` contract is
    unchanged so callers and the existing test surface keep working, but the
    provider is the Learner Domain repository: each ``save`` is a fresh
    DomainCommit (version +1, receipt + audit event), and reads come from the
    single authoritative aggregate row.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._root.mkdir(parents=True, exist_ok=True)
        self._ensure_repo()

    def _ensure_repo(self) -> None:
        """Initialise lock, db path, repository and legacy migration lazily."""
        if getattr(self, "_repo", None) is not None:
            return
        self._lock = threading.RLock()
        self._db_path = self._root / "learner.db"
        from lumen.modes.learn.commit.repository import LearnerDomainRepository

        self._repo = LearnerDomainRepository(self._db_path)
        from lumen.modes.learn.commit.migration import migrate_learning_json

        migrate_learning_json(self._root, self._repo)

    def _commit_service(self):
        from lumen.modes.learn.commit.commit_service import DomainCommitService

        self._ensure_repo()
        return DomainCommitService(self._repo)

    @staticmethod
    def _validate_book_id(book_id: str) -> None:
        """Reject empty / path-traversal-bearing book ids (security boundary)."""
        if (
            not book_id
            or "/" in book_id
            or "\\" in book_id
            or ".." in book_id
            or ":" in book_id
        ):
            raise ValueError(f"Invalid book_id: {book_id!r}")

    def current_version(self, book_id: str) -> int:
        self._ensure_repo()
        return self._repo.current_version(book_id) or 0

    # ── public contract ─────────────────────────────────────────────────

    def save(self, progress: LearningProgress) -> None:
        """Atomically commit the aggregate state (a fresh DomainCommit)."""
        from lumen.modes.learn.commit.contract import DomainCommitRequest

        self._ensure_repo()
        with self._lock:
            progress.updated_at = time.time()
            progress.version += 1
            learner = progress.book_id
            self._validate_book_id(learner)
            expected = self._repo.current_version(learner) or 0
            request = DomainCommitRequest(
                learner_id=learner,
                action_id=str(_uuid.uuid4()),
                expected_learner_version=expected,
                proposed_state=progress.model_dump(mode="json"),
            )
            self._commit_service().commit(request)

    def load(self, book_id: str) -> LearningProgress | None:
        self._validate_book_id(book_id)
        self._ensure_repo()
        agg = self._repo.get_aggregate(book_id)
        if agg is None:
            return None
        import json as _json

        return LearningProgress.model_validate(_json.loads(agg["state_json"]))

    def delete(self, book_id: str) -> None:
        self._validate_book_id(book_id)
        self._ensure_repo()
        with self._lock:
            self._repo.delete_aggregate(book_id)

    def reset(self, book_id: str) -> None:
        """Clear all learner history for *book_id* (a fresh-start reset)."""
        self._validate_book_id(book_id)
        self._ensure_repo()
        with self._lock:
            self._repo.delete_aggregate(book_id)

    def exists(self, book_id: str) -> bool:
        self._validate_book_id(book_id)
        self._ensure_repo()
        return self._repo.exists(book_id)

    def list_all(self) -> list[str]:
        self._ensure_repo()
        return self._repo.list_learner_ids()

    def close(self) -> None:
        self._ensure_repo()
        self._repo.close()


def _default_root() -> Path:
    return get_path_service().get_workspace_dir() / "learning"
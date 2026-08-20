"""Production Operations — capacity & data-lifecycle visibility.

Answers "how much disk is the runtime using and is it staying inside the
documented lifecycle" without touching business logic. Reads the frozen
data layout from ``PathService`` and reports:

* byte sizes of the data tree (workspace root, user data, logs, telemetry,
  metrics, SQLite, knowledge bases);
* retention status of the self-managed log/telemetry/metrics files
  (oldest/newest file dates, retention windows from the observability
  constants);
* a soft capacity boundary flag so an operator can detect unbounded growth
  before it becomes a disk-full incident.

Everything here is read-only and best-effort — a missing directory reports
zero, never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lumen.shared._util.observability.backend import DEFAULT_TELEMETRY_RETENTION_DAYS

__all__ = [
    "dir_size",
    "walk_sizes",
    "retention_status",
    "capacity_report",
    "LogRetention",
]

#: Default soft boundary for the whole runtime data tree (bytes). An operator
#: can override with ``LUMEN_CAPACITY_SOFT_MAX_BYTES``.
DEFAULT_SOFT_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB

#: Metrics summaries rotate daily and are pruned alongside telemetry.
METRICS_RETENTION_DAYS = DEFAULT_TELEMETRY_RETENTION_DAYS


def dir_size(path: str | Path) -> int:
    """Total size in bytes of a file or directory tree (best-effort)."""
    root = Path(path)
    if not root.exists():
        return 0
    if root.is_file():
        try:
            return root.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for child in root.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def walk_sizes(root: str | Path, top: int = 20) -> list[dict[str, Any]]:
    """Largest immediate subdirectories under *root* (for growth triage)."""
    base = Path(root)
    if not base.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            entries.append(
                {
                    "path": str(child),
                    "bytes": dir_size(child),
                }
            )
    except OSError:
        return []
    entries.sort(key=lambda e: e["bytes"], reverse=True)
    return entries[:top]


class LogRetention:
    """Retention limits for the self-managed lifecycle (log / telemetry / metrics)."""

    def __init__(
        self,
        *,
        app_log_rotation: str = "10 MB x 5",
        telemetry_days: int = DEFAULT_TELEMETRY_RETENTION_DAYS,
        metrics_days: int = METRICS_RETENTION_DAYS,
    ) -> None:
        self.app_log_rotation = app_log_rotation
        self.telemetry_days = telemetry_days
        self.metrics_days = metrics_days

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_log": self.app_log_rotation,
            "telemetry_days": self.telemetry_days,
            "metrics_days": self.metrics_days,
        }


def _file_dates(path: Path, pattern: str) -> tuple[int, int, list[str]]:
    """Return (oldest_mtime, newest_mtime, names) for matching files."""
    try:
        matches = [p for p in path.glob(pattern) if p.is_file()]
    except OSError:
        return 0, 0, []
    if not matches:
        return 0, 0, []
    mtimes = sorted(p.stat().st_mtime for p in matches)
    return int(mtimes[0]), int(mtimes[-1]), sorted(p.name for p in matches)


def retention_status(
    logs_dir: str | Path,
    *,
    retention: LogRetention | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Report retention health of telemetry/metrics under *logs_dir*.

    ``now`` is injectable for deterministic tests. Returns per-family file
    counts, oldest/newest dates, and whether the newest file is fresh (written
    within the retention window), which is the signal that the local pipeline
    is still producing output.
    """
    retention = retention or LogRetention()
    logs = Path(logs_dir)
    current = now if now is not None else datetime.now(timezone.utc).timestamp()

    def _family(pattern: str, window_days: int) -> dict[str, Any]:
        oldest, newest, names = _file_dates(logs, pattern)
        fresh = newest >= current - window_days * 86400
        return {
            "files": len(names),
            "oldest_mtime": oldest,
            "newest_mtime": newest,
            "fresh": bool(fresh),
            "window_days": window_days,
            "names": names,
        }

    return {
        "telemetry": _family("telemetry/*.jsonl", retention.telemetry_days),
        "metrics": _family("metrics/*.jsonl", retention.metrics_days),
        "log": _family("lumen.log", retention.telemetry_days),
    }


def capacity_report(
    path_service: Any,
    *,
    soft_max_bytes: int = DEFAULT_SOFT_MAX_BYTES,
) -> dict[str, Any]:
    """Build the canonical capacity report for a path service.

    ``path_service`` exposes ``workspace_root`` / ``get_user_root`` /
    ``get_logs_dir`` / ``get_chat_history_db`` / ``get_knowledge_bases_root``.
    """
    try:
        workspace_root = Path(path_service.workspace_root)
    except Exception:  # pragma: no cover - environment dependent
        workspace_root = None

    try:
        user_root = Path(path_service.get_user_root())
    except Exception:  # pragma: no cover
        user_root = None

    logs_dir = (user_root / "logs") if user_root is not None else None

    data_bytes = dir_size(workspace_root) if workspace_root is not None else 0
    user_bytes = dir_size(user_root) if user_root is not None else 0
    logs_bytes = dir_size(logs_dir) if logs_dir is not None else 0
    db_path = None
    db_bytes = 0
    if user_root is not None:
        db_path = user_root / "chat_history.db"
        db_bytes = dir_size(db_path)
    kb_bytes = 0
    if workspace_root is not None:
        try:
            kb_bytes = dir_size(path_service.get_knowledge_bases_root())
        except Exception:  # pragma: no cover
            kb_bytes = 0

    telemetry_bytes = dir_size((logs_dir / "telemetry")) if logs_dir is not None else 0
    metrics_bytes = dir_size((logs_dir / "metrics")) if logs_dir is not None else 0

    retention: dict[str, Any] = {}
    if logs_dir is not None:
        retention = retention_status(logs_dir)

    return {
        "bytes": {
            "data_total": data_bytes,
            "user_data": user_bytes,
            "logs": logs_bytes,
            "telemetry": telemetry_bytes,
            "metrics": metrics_bytes,
            "chat_history_db": db_bytes,
            "knowledge_bases": kb_bytes,
        },
        "soft_max_bytes": soft_max_bytes,
        "within_capacity": bool(data_bytes <= soft_max_bytes),
        "largest_subdirs": walk_sizes(workspace_root) if workspace_root is not None else [],
        "retention": retention,
        "retention_policy": LogRetention().to_dict(),
        "chat_history_db": str(db_path) if db_path is not None else None,
        "reported_at": datetime.now(timezone.utc).isoformat(),
    }

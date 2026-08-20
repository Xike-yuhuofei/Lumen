"""Production Operations health-monitor tests.

Verifies :func:`build_health_report` combines the SLI report, the live
persistence/telemetry probes and the capacity report into one status, and that
a stale telemetry pipeline / persistence failure / capacity breach each force
a non-ok overall status.
"""

from __future__ import annotations

from pathlib import Path

from lumen.ops.monitor import build_health_report, overall_status, telemetry_health
from lumen.ops.sli import SLI_STATUS_CRITICAL, SLI_STATUS_OK, SLI_STATUS_WARN, SLOConfig
from lumen.shared._util.observability import MetricsSnapshot


def _snap(counters: dict[str, int]) -> MetricsSnapshot:
    return MetricsSnapshot(dict(counters), {})


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root
        (root / "user" / "logs" / "telemetry").mkdir(parents=True, exist_ok=True)
        (root / "user" / "logs" / "metrics").mkdir(parents=True, exist_ok=True)
        (root / "knowledge_bases").mkdir(parents=True, exist_ok=True)

    @property
    def workspace_root(self) -> Path:
        return self._root

    def get_user_root(self) -> Path:
        return self._root / "user"

    def get_logs_dir(self) -> Path:
        return self._root / "user" / "logs"

    def get_knowledge_bases_root(self) -> Path:
        return self._root / "knowledge_bases"


def _healthy_snapshot() -> MetricsSnapshot:
    return _snap({"turn.completed": 100, "llm.total": 100, "tool.total": 20})


def test_healthy_report(tmp_path: Path) -> None:
    report = build_health_report(
        snapshot=_healthy_snapshot(),
        persistence_ok=True,
        path_service=_FakePathService(tmp_path),
    )
    assert report["status"] == SLI_STATUS_OK
    assert report["healthy"] is True
    assert report["sli"]["slis"]["persistence"]["status"] == SLI_STATUS_OK
    assert report["telemetry"]["ok"] is True
    assert report["capacity"]["within_capacity"] is True


def test_persistence_failure_forces_critical(tmp_path: Path) -> None:
    report = build_health_report(
        snapshot=_healthy_snapshot(),
        persistence_ok=False,
        path_service=_FakePathService(tmp_path),
    )
    assert report["status"] == SLI_STATUS_CRITICAL
    assert report["healthy"] is False
    assert report["sli"]["slis"]["persistence"]["status"] == SLI_STATUS_CRITICAL


def test_stale_telemetry_forces_critical(tmp_path: Path) -> None:
    _FakePathService(tmp_path)
    telemetry_dir = tmp_path / "user" / "logs" / "telemetry"
    stale = telemetry_dir / "2020-01-01.jsonl"
    stale.write_text("{}")
    old = 1577836800  # 2020-01-01 UTC
    import os

    os.utime(stale, (old, old))
    report = build_health_report(
        snapshot=_healthy_snapshot(),
        persistence_ok=True,
        path_service=_FakePathService(tmp_path),
    )
    assert report["telemetry"]["ok"] is False
    assert report["status"] == SLI_STATUS_CRITICAL


def test_capacity_breach_forces_critical(tmp_path: Path) -> None:
    # fill the tree so data_total exceeds a tiny soft max
    (tmp_path / "big.bin").write_bytes(b"x" * 4096)
    report = build_health_report(
        snapshot=_healthy_snapshot(),
        persistence_ok=True,
        path_service=_FakePathService(tmp_path),
        soft_max_bytes=1024,
    )
    assert report["capacity"]["within_capacity"] is False
    assert report["status"] == SLI_STATUS_CRITICAL


def test_warn_rollup(tmp_path: Path) -> None:
    slo = SLOConfig(llm_error_max=0.05, warn_factor=0.5)
    snap = _snap({"turn.completed": 100, "llm.total": 100, "llm.errors": 4})
    report = build_health_report(
        snapshot=snap, persistence_ok=True, slo=slo, path_service=_FakePathService(tmp_path)
    )
    assert report["sli"]["slis"]["llm"]["status"] == SLI_STATUS_WARN
    assert report["status"] == SLI_STATUS_WARN
    assert report["healthy"] is False


def test_overall_status_ranking() -> None:
    ok_report = {"status": SLI_STATUS_OK}
    assert overall_status(ok_report, telemetry_ok=True, capacity_ok=True) == SLI_STATUS_OK
    assert (
        overall_status({"status": SLI_STATUS_WARN}, telemetry_ok=True, capacity_ok=True)
        == SLI_STATUS_WARN
    )
    assert (
        overall_status({"status": SLI_STATUS_OK}, telemetry_ok=False, capacity_ok=True)
        == SLI_STATUS_CRITICAL
    )
    assert (
        overall_status({"status": SLI_STATUS_OK}, telemetry_ok=True, capacity_ok=False)
        == SLI_STATUS_CRITICAL
    )


def test_telemetry_health_missing_logs(tmp_path: Path) -> None:
    health = telemetry_health(tmp_path / "no-logs")
    assert health["ok"] is True
    assert health["files"] == 0

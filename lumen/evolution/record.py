"""Experiment record — mandatory reproducibility/lineage metadata.

Every Runtime Provider experiment MUST capture these fields so any result can
be reproduced.  The record is the audit/lineage unit: it pins provider,
version, git_commit, benchmark_version, model, toolset, teaching_plugins,
input_dataset, seed, environment, metrics, trace, and timestamp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExperimentRecord:
    """One benchmarked provider-run (one scenario × one rep × one provider)."""

    provider_id: str
    provider_version: str
    git_commit: str
    benchmark_version: str
    scenario_id: str
    model: str
    model_config: dict[str, Any] = field(default_factory=dict)
    toolset: list[str] = field(default_factory=list)
    teaching_plugins: list[str] = field(default_factory=list)
    input_dataset: str = ""
    seed: int | None = None
    environment: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    trace: list[Any] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def lineage_key(self) -> tuple[str, ...]:
        """Stable identifier for reproducibility (excludes metrics/trace/timestamp)."""
        return (
            self.provider_id,
            self.provider_version,
            self.git_commit,
            self.benchmark_version,
            self.scenario_id,
            self.model,
            self.input_dataset,
            str(self.seed),
            self.environment,
        )


def current_git_commit() -> str:
    """Best-effort short git HEAD for the record; empty when unavailable."""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=".",
            timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


__all__ = ["ExperimentRecord", "current_git_commit"]
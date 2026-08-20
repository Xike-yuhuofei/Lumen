"""Architecture gate tests for the observability module (v1).

Observability lives in ``lumen/shared/_util/observability`` — a private
shared utility namespace that runtime / modes / app may import without
violating the existing plugin-ownership gates. Two additional rules are
guarded here:

* Kernel must never import observability (keeps the kernel pure).
* Observability must never import ``lumen.runtime`` / ``lumen.modes``
  (it is layer-agnostic infrastructure that only depends on shared itself).
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

LUMEN_ROOT = Path(__file__).resolve().parents[2] / "lumen"
OBSERVABILITY_DIR = LUMEN_ROOT / "shared" / "_util" / "observability"

_IMPORT_LINE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)\b")

OBSERVABILITY_ROOT = "lumen.shared._util.observability"


def _import_targets(path: Path) -> list[str]:
    targets: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _IMPORT_LINE.match(raw)
        if not m:
            continue
        targets.append((m.group(1) or m.group(2)).lstrip("."))
    return targets


def _references(modules: list[str], forbidden: tuple[str, ...]) -> list[str]:
    return [
        mod
        for mod in modules
        if any(mod == f or mod.startswith(f + ".") for f in forbidden)
    ]


def test_kernel_does_not_import_observability() -> None:
    violations: list[tuple[Path, str]] = []
    for py in sorted((LUMEN_ROOT / "kernel").rglob("*.py")):
        for mod in _references(_import_targets(py), (OBSERVABILITY_ROOT,)):
            violations.append((py.relative_to(LUMEN_ROOT.parent), mod))
    assert not violations, "Kernel imports observability:\n" + "\n".join(
        f"{rel}:{mod}" for rel, mod in violations
    )


def test_observability_does_not_import_runtime_or_modes() -> None:
    forbidden = ("lumen.runtime", "lumen.modes")
    violations: list[tuple[Path, str]] = []
    for py in sorted(OBSERVABILITY_DIR.rglob("*.py")):
        for mod in _references(_import_targets(py), forbidden):
            violations.append((py.relative_to(LUMEN_ROOT.parent), mod))
    assert not violations, "Observability imports runtime/modes:\n" + "\n".join(
        f"{rel}:{mod}" for rel, mod in violations
    )


def test_observability_module_files_present() -> None:
    expected = {"__init__.py", "backend.py", "context.py", "metrics.py", "redact.py", "span.py"}
    present = {p.name for p in OBSERVABILITY_DIR.glob("*.py")}
    assert expected <= present, f"missing observability modules: {expected - present}"


@pytest.mark.parametrize(
    "producer",
    [
        "lumen/runtime/session/turn_runtime.py",
        "lumen/app/api/routers/unified_ws.py",
        "lumen/app/cron/executor.py",
    ],
)
def test_turn_entries_may_import_observability(producer: str) -> None:
    """Runtime/app turn entries may consume observability (allowed util)."""
    path = LUMEN_ROOT.parent / producer
    assert path.exists(), f"producer missing: {producer}"
    assert any(
        mod == OBSERVABILITY_ROOT or mod.startswith(OBSERVABILITY_ROOT + ".")
        for mod in _import_targets(path)
    ), f"{producer} does not wire observability (expected a correlation binding)"

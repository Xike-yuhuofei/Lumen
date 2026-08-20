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


@pytest.mark.parametrize(
    "producer",
    [
        # Candidate 2 execution-chain instrumentation points. Each must consume
        # observability through the shared private util namespace only — never
        # a runtime/modes provider — so switching agent-loop providers or
        # editing mode internals cannot break the observability contract.
        "lumen/runtime/agent_loop/engine/client.py",
        "lumen/runtime/tools/registry.py",
        "lumen/runtime/tools/scoped_registry.py",
        "lumen/runtime/session/sqlite_store.py",
        "lumen/shared/knowledge/rag/service.py",
        "lumen/shared/_util/llm/provider_core/base.py",
        "lumen/modes/learn/policy/engine.py",
        "lumen/modes/learn/commit/commit_service.py",
        "lumen/modes/learn/commit/outbox.py",
    ],
)
def test_instrumentation_imports_observability_contract(producer: str) -> None:
    """Instrumented modules depend on the observability contract, not a backend.

    The reverse constraints (runtime/shared never import modes, modes never
    import runtime providers) are already enforced by the phase-7 gates
    (``test_architecture_gates_phase7.py``); this test only guards that the
    execution-chain instrumentation keeps consuming the observability contract.
    """
    path = LUMEN_ROOT.parent / producer
    assert path.exists(), f"instrumented module missing: {producer}"
    targets = _import_targets(path)
    assert any(
        mod == OBSERVABILITY_ROOT or mod.startswith(OBSERVABILITY_ROOT + ".")
        for mod in targets
    ), f"{producer} lost its observability contract dependency"

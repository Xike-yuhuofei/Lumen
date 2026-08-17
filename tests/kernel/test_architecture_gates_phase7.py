"""Architecture gate tests — preserve the frozen plugin architecture.

These tests guard the ownership rules from the Phase 7 finalization goal by
statically scanning ``lumen/`` source for forbidden dependency edges.  They are
design guards, not behaviour tests: a violation fails fast so an accidental
provider / implementation coupling cannot silently re-enter the kernel or a
mode.

Rules enforced here:
  * Kernel (``lumen/kernel/**``) must not import any domain implementation
    (agent / llm / rag / learning / teaching / learn / news / review).
  * ``mode.learn`` must not import a concrete runtime provider (langchain /
    langgraph / a specific LLM provider / LlamaIndex impl / Legacy Agent Loop
    impl) — it may only touch the injected contracts.
  * ``mode.learn`` must not import the implementation of another plugin
    (``lumen.runtime.*`` / ``lumen.shared.*`` provider modules); it depends on
    contracts resolved through the ``PluginContext``.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

LUMEN_ROOT = Path(__file__).resolve().parents[2] / "lumen"
KERNEL_DIR = LUMEN_ROOT / "kernel"
MODE_LEARN_DIR = LUMEN_ROOT / "modes" / "learn"

# A compiled matcher for python import/from lines.
_IMPORT_LINE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)\b")


def _rel(file: Path) -> str:
    return file.relative_to(LUMEN_ROOT.parent).as_posix()


def _import_targets(path: Path) -> list[str]:
    """Return the module roots targeted by import/from lines in *path*."""
    targets: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = _IMPORT_LINE.match(raw)
        if not m:
            continue
        module = m.group(1) or m.group(2)
        # Strip leading dots from relative imports.
        module = module.lstrip(".")
        if not module:
            continue
        targets.append(f"{_rel(path)}:{lineno}:{module}")
    return targets


def _forbidden(targets: list[str], needles: tuple[str, ...]) -> list[str]:
    """Return the targets that reference one of *needles* as a prefix."""
    out: list[str] = []
    for t in targets:
        module = t.split(":", 2)[2]
        if any(module == n or module.startswith(n + ".") for n in needles):
            out.append(t)
    return out


# ── Kernel ───────────────────────────────────────────────────────────────

KERNEL_FORBIDDEN = ("agent", "llm", "rag", "learning", "teaching", "learn", "news", "review")


def test_kernel_does_not_import_domain_implementations() -> None:
    violations: list[str] = []
    for py in sorted(KERNEL_DIR.rglob("*.py")):
        violations += _forbidden(_import_targets(py), KERNEL_FORBIDDEN)
    assert not violations, "Kernel imports a domain implementation:\n" + "\n".join(violations)


# ── mode.learn ───────────────────────────────────────────────────────────

MODE_FORBIDDEN_PROVIDER_IMPORTS = (
    # agent-loop / reasoning frameworks a mode must never couple to
    "langchain",
    "langgraph",
    "llamaindex",
    # the legacy namespace is not a truth a mode may depend on
    "deeptutor",
)


def test_mode_learn_does_not_import_concrete_provider_implementations() -> None:
    violations: list[str] = []
    for py in sorted(MODE_LEARN_DIR.rglob("*.py")):
        violations += _forbidden(_import_targets(py), MODE_FORBIDDEN_PROVIDER_IMPORTS)
    assert not violations, "mode.learn imports a concrete provider:\n" + "\n".join(violations)


def test_mode_learn_does_not_import_other_plugins_providers() -> None:
    """mode.learn depends on contracts (injected), never another plugin's provider.

    Pure private utilities under a leading-underscore segment (e.g.
    ``lumen.shared._util.*``) are not provider implementations and are allowed.
    """
    violations: list[str] = []
    needles = {"runtime", "shared"}
    for py in sorted(MODE_LEARN_DIR.rglob("*.py")):
        for t in _import_targets(py):
            module = t.split(":", 2)[2]
            parts = module.split(".")
            # only flag module roots that are lumen.runtime*/lumen.shared*
            if len(parts) >= 2 and parts[0] == "lumen" and parts[1] in needles:
                if _is_private_util(parts[2:]):
                    continue
                violations.append(t)
    assert not violations, "mode.learn imports another plugin's provider:\n" + "\n".join(violations)


def _is_private_util(rest: list[str]) -> bool:
    """True if any remaining path segment is a private utility namespace (``_x``)."""
    return any(segment.startswith("_") for segment in rest)


# ── No plugin import cycle sanity ──────────────────────────────────────────
#
# The kernel is the only thing every plugin may import; plugins may import
# their own subtree and the kernel, never a sibling plugin's provider modules.

PLUGIN_ROOTS = [
    LUMEN_ROOT / "runtime",
    LUMEN_ROOT / "shared",
    LUMEN_ROOT / "modes",
]
SIBLING_BY_ROOT = {
    "runtime": {"shared", "modes"},
    "shared": {"runtime", "modes"},
    "modes": {"runtime", "shared"},
}


@pytest.mark.parametrize("root", PLUGIN_ROOTS)
def test_plugin_providers_do_not_cross_import_sibling_providers(root: Path) -> None:
    own = {p.name for p in PLUGIN_ROOTS if p is not root}
    violations: list[str] = []
    for py in sorted(root.rglob("*.py")):
        for t in _import_targets(py):
            module = t.split(":", 2)[2]
            parts = module.split(".")
            if len(parts) >= 2 and parts[0] == "lumen" and parts[1] in own:
                if _is_private_util(parts[2:]):
                    continue
                violations.append(t)
    assert not violations, f"{root.name}/* imports a sibling plugin provider:\n" + "\n".join(
        violations
    )


# ── Legacy capability shell removed ─────────────────────────────────────────
#
# The multi-capability product entry (ChatOrchestrator, ChatCapability,
# CapabilityRegistry, BUILTIN_CAPABILITY_CLASSES, BaseCapability) has been
# removed.  No production source may import or reference it, and the module
# files must no longer exist.

LEGACY_CAPABILITY_IMPORTS = (
    "deeptutor.runtime.orchestrator",
    "deeptutor.runtime.registry.capability_registry",
    "deeptutor.runtime.bootstrap.builtin_capabilities",
    "deeptutor.agents.chat.capability",
    "deeptutor.core.capability_protocol",
)

LEGACY_CAPABILITY_FILES = (
    "deeptutor/runtime/orchestrator.py",
    "deeptutor/runtime/registry/capability_registry.py",
    "deeptutor/runtime/bootstrap/builtin_capabilities.py",
    "deeptutor/agents/chat/capability.py",
    "deeptutor/core/capability_protocol.py",
)

LUMEN_ROOT_PARENT = LUMEN_ROOT.parent


def test_legacy_capability_shell_modules_removed() -> None:
    """The legacy capability registration/routing shell files must be gone."""
    present = [
        _rel(LUMEN_ROOT_PARENT / f)
        for f in LEGACY_CAPABILITY_FILES
        if (LUMEN_ROOT_PARENT / f).exists()
    ]
    assert not present, "Legacy capability shell still present:\n" + "\n".join(present)


def _production_py_files() -> list[Path]:
    out: list[Path] = []
    for root in ("deeptutor", "lumen"):
        out.extend((LUMEN_ROOT_PARENT / root).rglob("*.py"))
    return out


# ── Dependency direction: Runtime / Shared never know the modes ─────────────
#
# Runtime and Shared are mode-agnostic infrastructure: they must not import
# ``lumen.modes.*`` (or any mode implementation), so a mode can be added or
# removed without touching the layers below it.

RUNTIME_DIR = LUMEN_ROOT / "runtime"
SHARED_DIR = LUMEN_ROOT / "shared"
MODES_DIR = LUMEN_ROOT / "modes"


def test_runtime_does_not_import_modes() -> None:
    violations: list[str] = []
    for py in sorted(RUNTIME_DIR.rglob("*.py")):
        violations += _forbidden(_import_targets(py), ("lumen.modes",))
    assert not violations, "Runtime imports a mode implementation:\n" + "\n".join(violations)


def test_shared_does_not_import_modes_or_runtime_providers() -> None:
    violations: list[str] = []
    for py in sorted(SHARED_DIR.rglob("*.py")):
        violations += _forbidden(_import_targets(py), ("lumen.modes", "lumen.runtime"))
    assert not violations, "Shared imports a mode / runtime provider:\n" + "\n".join(violations)


# ── No mode.chat — generic agent turns belong to Runtime ────────────────────
#
# ``chat`` is not a product mode: a generic agent turn routes straight into
# the ``runtime.agent_loop`` contract.  The only product mode directory is
# ``learn`` (future: news / review).


def test_no_chat_mode_exists() -> None:
    mode_dirs = sorted(
        p.name for p in MODES_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    assert "chat" not in mode_dirs, "mode.chat must never exist — generic turns belong to Runtime"
    assert mode_dirs == ["learn"], f"unexpected mode directories: {mode_dirs}"


# ── Unified Runtime entry for generic turns ─────────────────────────────────
#
# The turn-execution entries (WS turn runtime, Cron executor) must run turns
# through the Plugin Kernel's ``runtime.agent_loop`` contract — they must not
# instantiate the chat pipeline directly to execute a turn.

TURN_ENTRY_FILES = (
    "deeptutor/services/session/turn_runtime.py",
    "deeptutor/services/cron/executor.py",
)
DIRECT_PIPELINE_IMPORTS = ("deeptutor.agents.chat.agentic_pipeline",)


@pytest.mark.parametrize("rel", TURN_ENTRY_FILES)
def test_turn_entries_use_runtime_contract_not_direct_pipeline(rel: str) -> None:
    path = LUMEN_ROOT_PARENT / rel
    assert path.exists(), f"turn entry missing: {rel}"
    violations = _forbidden(_import_targets(path), DIRECT_PIPELINE_IMPORTS)
    assert not violations, (
        f"{rel} runs turns through a directly-imported pipeline instead of the "
        "runtime.agent_loop contract:\n" + "\n".join(violations)
    )


@pytest.mark.parametrize("legacy", LEGACY_CAPABILITY_IMPORTS)
def test_no_production_import_of_legacy_capability_shell(legacy: str) -> None:
    violations: list[str] = []
    for py in _production_py_files():
        for t in _import_targets(py):
            module = t.split(":", 2)[2]
            if module == legacy or module.startswith(legacy + "."):
                violations.append(t)
    assert not violations, f"production imports legacy capability shell ({legacy}):\n" + "\n".join(
        violations
    )

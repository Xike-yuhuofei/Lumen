"""Packaging regressions: the kernel must ship in the wheel (Phase 1.5)."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import subprocess
import sys
import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)


def test_wheel_discovery_include_covers_lumen() -> None:
    include = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]
    assert any(fnmatch("lumen.kernel", pattern) for pattern in include), (
        f"setuptools package discovery no longer matches lumen.kernel: {include}"
    )


def test_setuptools_discovery_finds_kernel_packages() -> None:
    pytest = __import__("pytest")
    pytest.importorskip("setuptools")
    from setuptools import find_packages

    packages = set(find_packages(str(REPOSITORY_ROOT)))
    assert {"lumen", "lumen.kernel"} <= packages


def test_ruff_treats_lumen_as_first_party() -> None:
    known_first_party = _pyproject()["tool"]["ruff"]["lint"]["isort"]["known-first-party"]
    assert "lumen" in known_first_party


def test_kernel_importable_from_repository_root() -> None:
    """Simulates the installed-wheel import path: a bare interpreter in the
    project root resolves ``lumen.kernel`` exactly like site-packages would."""

    result = subprocess.run(
        [sys.executable, "-c", "import lumen.kernel; print(lumen.kernel.__all__)"],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Bootstrap" in result.stdout

"""Lumen Evolution Harness v0.1.

A controlled, reproducible arena in which alternative Agent Runtime
Providers (Legacy, LangGraph thin / teaching-nodes / dual) are evaluated,
compared on a common contract + benchmark, kept in a Pareto archive, and
promoted to production only through an auditable Promotion Gate.

This package is **strictly separate** from the production profile: it
imports runtime contracts and teaching contracts but never modifies the
production Provider, the frozen Bake-off v1, the Promotion Gate, the test
oracle, or the safety boundary.
"""

from __future__ import annotations

__version__ = "0.1.0"
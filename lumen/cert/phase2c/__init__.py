"""Phase 2C — Adaptive Teaching Strategy Selection.

Canonical home: ``lumen/cert/phase2c``.

Reuses the Phase 1 Frozen Baseline, the Phase 2A/2B candidate machinery and the
shared CertificationStore / Evaluators / Tutor / Simulator planes. It adds:

1. **AdaptiveStrategySelector** — a deterministic, auditable per-turn strategy
   choice from *public* learner behaviour (`adaptive.py`).
2. **AdaptiveLumenTutor** — wraps the real Lumen Tutor, injecting the selected
   strategy per turn and recording every decision.
3. A real comparison of **baseline / fixed socratic-questions / adaptive** across
   multiple discriminating scenarios and repeated trials, with a promotion
   decision that enforces *value genuinely from selection* (anti-degeneration).

Status marker is finalized after the real multi-trial run.
"""

#: Phase 2C status — finalized after the real multi-trial run: **KEEP CURRENT
#: STRATEGY / CONTINUE EXPERIMENT**. Evidence: ``data/user/workspace/runtime/
#: phase2c_outcome.json`` (27 real cells; adaptive not promoted because it does
#: not beat both fixed arms).
PHASE2C_STATUS = "KEEP CURRENT STRATEGY / CONTINUE EXPERIMENT"

__all__ = ["PHASE2C_STATUS"]
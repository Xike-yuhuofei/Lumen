"""Phase 2A — Teaching Strategy Optimization.

Canonical home: ``lumen/cert/phase2``.

Runs systematic, fair comparisons of the **Phase 1 Frozen Baseline** against new
Teaching Strategies across a small set of **discriminating** scenarios, using the
existing real Lumen Tutor / Learner Simulator / Evaluators / CertificationStore.
Phase 1 ``FROZEN_BASELINE`` is protected: the machine only varies
``prompt_override`` (+ temperature), never the Rubric / Evaluators / Simulator /
Regression / Certification semantics.

Scope is **Teaching Behavior Quality / Long-Horizon Teaching Stability only**.
No claim is made about real Learning Gain / Retention / Transfer / student
effect. If no candidate is stably better, the honest conclusion is
**KEEP BASELINE / CONTINUE EXPERIMENT** (no forced promotion).
"""

#: Phase 2A status — the real-LLM matrix completed with the honest verdict
#: **KEEP BASELINE / CONTINUE EXPERIMENT** (no candidate met the promotion bar;
#: see ``data/user/workspace/runtime/phase2a_outcome.json`` and its ``decision``).
PHASE2A_STATUS = "KEEP BASELINE / CONTINUE EXPERIMENT"

__all__ = ["PHASE2A_STATUS"]

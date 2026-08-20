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

#: Phase 2A status — updated after each real run; a definitive report should
#: replace this with ``KEEP BASELINE / CONTINUE EXPERIMENT`` or
#: ``PROMOTE CANDIDATE``.
PHASE2A_STATUS = "RUNNING"

__all__ = ["PHASE2A_STATUS"]
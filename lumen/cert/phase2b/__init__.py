"""Phase 2B — Teaching Strategy Stability & Regression Contract Validation.

Canonical home: ``lumen/cert/phase2b``.

Phase 2B reuses the Phase 1 Frozen Baseline, the Phase 2A candidate machinery
(``lumen.cert.phase2.scenarios.build_candidate`` and
``lumen.cert.phase2.compare.run_episode``) and the shared CertificationStore /
Evaluators / Tutor / Simulator planes — it does **not** build a parallel
experiment system. Two deliverables:

1. **Regression Contract** — the old absolute ``prompt_override > 4000`` cap in
   ``lumen.cert.regression._check_candidate_wellformed`` was inconsistent with
   the current Frozen Baseline (en real prompt = 5153 chars), so it blocked every
   legitimate additive candidate. It is now expressed relative to the Frozen
   Baseline prompt (see the checker's NOTE).
2. **socratic-questions multi-trial stability** — whether the Phase 2A real run's
   ``socratic-questions`` edge (better in 2/2 scenarios, but blocked from
   promotion) survives repeated trials and multiple related-but-different
   misconception-correction scenarios, judged on trial-level pass-rate evidence,
   not a single trajectory or a single evaluator call.

Scope is **Teaching Behaviour Quality / Long-Horizon Teaching Stability only**.
No claim about real Learning Gain / Retention / Transfer is made. If the
advantage is not stable across scenarios and trials, the honest verdict is
**KEEP BASELINE / CONTINUE EXPERIMENT**.
"""

#: Phase 2B status — finalized after the real multi-trial run:
#: **PROMOTE CANDIDATE (socratic-questions)**. Backed by 12 real cells
#: (go-concurrency + sampling-bias, 3 trials each, baseline vs socratic), with the
#: Regression Contract corrected to be Baseline-relative and all promotion gates
#: passing. Evidence: ``data/user/workspace/runtime/phase2b_outcome.json``.
PHASE2B_STATUS = "PROMOTE CANDIDATE"

__all__ = ["PHASE2B_STATUS"]
"""Learn Mode evaluation harness — fixed benchmark set + learner simulators.

This package is the long-lived, machine-readable Learn Evaluation introduced
by the "Validate & Harden Learn Mode" goal. It owns:

* the fixed **Benchmark Set** (real materials -> module designs) in
  :mod:`~.materials`;
* the five learner simulators (strong / weak / misconception / guessing /
  forgetting) in :mod:`~.learners`;
* the deterministic loop driver over the production tool surface in
  :mod:`~.harness`.

The tests under :mod:`~.tests` (``test_learn_benchmark.py`` /
``test_learn_scenarios.py``) run these deterministically and assert the
teaching-quality acceptance criteria; ``run_benchmark.py`` dumps a
machine-readable JSON record for cross-run regression comparison.
"""

"""Pareto evaluation tests — no single-score masking; multiple providers may sit
on the frontier simultaneously."""

from __future__ import annotations

from lumen.evolution.pareto import (
    ParetoArchive,
    dominates,
    pareto_frontier,
)


def test_dominates_strictly_better_on_one_and_equal_or_better_on_rest():
    better = {"rt_output_quality": 1.0, "rt_step_count": 2, "rt_latency": 1.0}
    worse = {"rt_output_quality": 0.5, "rt_step_count": 2, "rt_latency": 1.0}
    assert dominates(better, worse)


def test_equal_on_all_axes_does_not_dominate():
    a = {"rt_output_quality": 1.0, "rt_step_count": 2}
    b = {"rt_output_quality": 1.0, "rt_step_count": 2}
    assert not dominates(a, b)


def test_lower_cost_axis_wins_when_lower_is_better():
    # Fewer steps is better (cost ↓ / complexity ↓)
    cheap = {"rt_step_count": 1}
    expensive = {"rt_step_count": 5}
    assert dominates(cheap, expensive)


def test_pareto_frontier_keeps_incomparable_candidates():
    a = {"rt_output_quality": 1.0, "rt_step_count": 10}  # high quality, costly
    b = {"rt_output_quality": 0.4, "rt_step_count": 1}  # low quality, cheap
    c = {"rt_output_quality": 0.2, "rt_step_count": 20}  # dominated by a
    front = pareto_frontier([a, b, c])
    assert front == [a, b]  # c dominated by a; a and b incomparable


def test_pareto_archive_evicts_dominated_members():
    archive = ParetoArchive()
    archive.add("cheap", {"rt_output_quality": 0.4, "rt_step_count": 1})
    archive.add("good_expensive", {"rt_output_quality": 1.0, "rt_step_count": 10})
    archive.add("dominated", {"rt_output_quality": 0.2, "rt_step_count": 20})
    assert "dominated" not in archive.provider_ids()
    # Both incomparable members stay on the frontier.
    assert set(archive.provider_ids()) == {"cheap", "good_expensive"}


def test_no_fused_single_score_in_archive():
    archive = ParetoArchive()
    archive.add("x", {"rt_output_quality": 1.0, "rt_step_count": 1})
    for member in archive.members():
        assert "score" not in member.metrics

"""Correlation is only honest next to the ceiling humans set for each other."""

from __future__ import annotations

import pytest

from veriquill.eval.ranking import (
    agreement,
    average_ranks,
    inter_rater_ceiling,
    kendall_tau_b,
    ranks_from_order,
    spearman,
)


def test_average_ranks_splits_ties_evenly():
    assert average_ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_is_one_for_identical_orderings():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_spearman_is_minus_one_for_reversed_orderings():
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_handles_ties_without_dividing_by_zero():
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, abs=1e-6)


def test_spearman_is_undefined_when_one_side_has_no_variance():
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_spearman_is_undefined_for_fewer_than_two_points():
    assert spearman([1], [1]) is None


def test_kendall_is_one_for_identical_orderings():
    assert kendall_tau_b([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_kendall_is_minus_one_for_reversed_orderings():
    assert kendall_tau_b([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_kendall_counts_a_single_swap_as_partial_agreement():
    tau = kendall_tau_b([1, 2, 3, 4], [1, 2, 4, 3])

    assert 0.0 < tau < 1.0


def test_ranks_from_order_numbers_from_the_top():
    assert ranks_from_order(["a", "b", "c"]) == {"a": 1.0, "b": 2.0, "c": 3.0}


def test_agreement_reports_both_coefficients_and_the_overlap_it_used():
    result = agreement({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3})

    assert result["spearman"] == pytest.approx(1.0)
    assert result["kendall_tau_b"] == pytest.approx(1.0)
    assert result["candidates_compared"] == 3


def test_agreement_uses_only_candidates_both_sides_ranked():
    result = agreement({"a": 1, "b": 2, "ghost": 3}, {"a": 1, "b": 2})

    assert result["candidates_compared"] == 2
    assert result["ignored"] == ["ghost"]


def test_agreement_on_a_single_shared_candidate_is_undefined_not_perfect():
    result = agreement({"a": 1}, {"a": 1})

    assert result["spearman"] is None
    assert result["kendall_tau_b"] is None


def test_a_tied_tool_ranking_still_correlates():
    result = agreement({"a": 1, "b": 1, "c": 3}, {"a": 1, "b": 2, "c": 3})

    assert result["spearman"] is not None
    assert result["spearman"] > 0


def test_the_inter_rater_ceiling_is_the_mean_pairwise_agreement():
    ceiling = inter_rater_ceiling(
        [["a", "b", "c"], ["a", "b", "c"], ["a", "c", "b"]]
    )

    assert ceiling["raters"] == 3
    assert ceiling["pairs"] == 3
    assert 0.0 < ceiling["mean_spearman"] < 1.0


def test_a_single_rater_sets_no_ceiling():
    ceiling = inter_rater_ceiling([["a", "b", "c"]])

    assert ceiling["mean_spearman"] is None
    assert "one" in ceiling["note"].lower() or "single" in ceiling["note"].lower()


def test_identical_raters_report_a_perfect_ceiling():
    ceiling = inter_rater_ceiling([["a", "b"], ["a", "b"]])

    assert ceiling["mean_spearman"] == pytest.approx(1.0)

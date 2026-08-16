import pytest

from veriquill.eval.metrics import CheckScore, calibration_bins, score_checks


def test_a_check_that_fires_exactly_where_expected_is_perfect():
    scores = score_checks(
        [
            ({"a"}, {"a"}),
            ({"a"}, {"a"}),
        ]
    )
    assert scores["a"].precision == 1.0
    assert scores["a"].recall == 1.0
    assert scores["a"].f1 == 1.0


def test_a_check_that_fires_when_it_should_not_loses_precision():
    scores = score_checks(
        [
            ({"a"}, {"a"}),
            ({"a"}, set()),  # fired on a clean case
        ]
    )
    assert scores["a"].false_positives == 1
    assert scores["a"].precision == 0.5
    assert scores["a"].recall == 1.0


def test_a_check_that_misses_loses_recall():
    scores = score_checks(
        [
            (set(), {"a"}),
            ({"a"}, {"a"}),
        ]
    )
    assert scores["a"].false_negatives == 1
    assert scores["a"].recall == 0.5
    assert scores["a"].precision == 1.0


def test_a_check_that_never_fires_and_is_never_expected_is_absent():
    assert "z" not in score_checks([({"a"}, {"a"})])


def test_precision_of_a_check_that_never_fires_is_reported_as_zero_not_nan():
    scores = score_checks([(set(), {"a"})])
    assert scores["a"].precision == 0.0
    assert scores["a"].f1 == 0.0


def test_scores_carry_the_raw_counts_for_auditing():
    score = score_checks([({"a"}, {"a"}), ({"a"}, set())])["a"]
    assert (score.true_positives, score.false_positives, score.false_negatives) == (1, 1, 0)


def test_empty_input_scores_nothing():
    assert score_checks([]) == {}


# --- calibration ---------------------------------------------------------


def test_a_perfectly_calibrated_set_matches_its_confidence():
    """Findings asserted at 0.9 confidence are right about 90% of the time."""
    observations = [(0.9, True)] * 9 + [(0.9, False)]
    bins = calibration_bins(observations, bin_count=5)

    bucket = next(b for b in bins if b.count)
    assert bucket.mean_confidence == pytest.approx(0.9)
    assert bucket.observed_accuracy == pytest.approx(0.9)
    assert bucket.gap == pytest.approx(0.0, abs=1e-9)


def test_overconfidence_shows_as_a_positive_gap():
    observations = [(0.95, False)] * 5 + [(0.95, True)] * 5
    bucket = next(b for b in calibration_bins(observations) if b.count)

    assert bucket.observed_accuracy == 0.5
    assert bucket.gap > 0  # claimed more confidence than it earned


def test_bins_without_observations_are_reported_empty_not_dropped():
    bins = calibration_bins([(0.95, True)], bin_count=4)
    assert len(bins) == 4
    assert sum(b.count for b in bins) == 1


def test_calibration_of_nothing_is_empty_bins():
    assert all(b.count == 0 for b in calibration_bins([]))


def test_check_score_is_serialisable():
    score = CheckScore(check_id="a", true_positives=1, false_positives=0, false_negatives=0)
    payload = score.to_dict()
    assert payload["check_id"] == "a"
    assert payload["precision"] == 1.0

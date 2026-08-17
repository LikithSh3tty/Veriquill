"""A number without its coverage is a lie of omission."""

from __future__ import annotations

import pytest

from tests.test_dimensions import flag, make_dossier
from veriquill.rank.score import score_candidate
from veriquill.rubric import DIMENSIONS, Rubric

RUBRIC = Rubric.from_dict({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})


def test_a_clean_fully_covered_candidate_scores_near_the_top():
    result = score_candidate(make_dossier(), RUBRIC)

    assert result.handle == "octocat"
    assert result.score > 0.5
    assert result.band[0] <= result.score <= result.band[1]


def test_unmeasured_dimensions_are_named_and_dropped_from_the_weighting():
    dossier = make_dossier(
        analysis_coverage={
            "repositories_considered": 1,
            "repositories_analysed": 1,
            "repositories_with_authored_code": 1,
            "repositories_deep_analysed": 0,
            "claims_total": 0,
            "claims_resolved": 0,
        }
    )

    result = score_candidate(dossier, RUBRIC)

    assert set(result.unmeasured) == {
        "code_quality",
        "test_quality",
        "security",
        "claim_corroboration",
    }
    assert result.score is not None


def test_a_dimension_that_could_not_be_measured_never_scores_zero():
    thin = score_candidate(
        make_dossier(
            analysis_coverage={
                "repositories_considered": 1,
                "repositories_analysed": 1,
                "repositories_with_authored_code": 1,
                "repositories_deep_analysed": 0,
                "claims_total": 0,
                "claims_resolved": 0,
            }
        ),
        RUBRIC,
    )
    full = score_candidate(make_dossier(), RUBRIC)

    assert thin.score == pytest.approx(full.score, abs=0.35)
    assert thin.confidence in ("low", "moderate", "high")


def test_lower_coverage_widens_the_band():
    full = score_candidate(make_dossier(), RUBRIC)
    partial = score_candidate(
        make_dossier(
            analysis_coverage={
                "repositories_considered": 4,
                "repositories_analysed": 1,
                "repositories_with_authored_code": 1,
                "repositories_deep_analysed": 1,
                "claims_total": 0,
                "claims_resolved": 0,
            }
        ),
        RUBRIC,
    )

    assert partial.width > full.width


def test_everything_unmeasured_is_reported_not_scored():
    dossier = make_dossier(
        code_quality_snapshot=[],
        analysis_coverage={
            "repositories_considered": 3,
            "repositories_analysed": 0,
            "repositories_with_authored_code": 0,
            "repositories_deep_analysed": 0,
            "claims_total": 0,
            "claims_resolved": 0,
        },
    )

    result = score_candidate(dossier, RUBRIC)

    assert result.score is None
    assert result.scored is False
    assert result.band == (0.0, 1.0)
    assert result.confidence == "low"
    assert set(result.unmeasured) == set(DIMENSIONS)


def test_a_zero_weight_dimension_is_excluded_rather_than_scored():
    rubric = Rubric.from_dict(
        {"name": "no-breadth", "weights": {"breadth": 0.0, "authenticity": 1.0}}
    )

    result = score_candidate(make_dossier(), rubric)

    assert "breadth" in result.unmeasured


def test_a_minimum_bar_breach_is_reported_and_does_not_zero_the_score():
    rubric = Rubric.from_dict(
        {
            "name": "strict",
            "weights": {d: 1.0 for d in DIMENSIONS},
            "minimum_bars": {"authenticity": 0.95},
        }
    )
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump", "critical")])

    result = score_candidate(dossier, rubric)

    assert "authenticity" in result.bar_breaches
    assert result.score > 0.0


def test_scoring_is_deterministic():
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump")])

    first = score_candidate(dossier, RUBRIC)
    second = score_candidate(dossier, RUBRIC)

    assert first.to_dict() == second.to_dict()


def test_dismissing_a_flag_raises_the_score_deterministically():
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump", flag_id="abc")])

    kept = score_candidate(dossier, RUBRIC)
    dismissed = score_candidate(dossier, RUBRIC, frozenset({"abc"}))

    assert dismissed.score > kept.score
    assert dismissed.to_dict() == score_candidate(dossier, RUBRIC, frozenset({"abc"})).to_dict()


def test_weights_shift_the_score_in_the_expected_direction():
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump", "critical")])

    authenticity_heavy = Rubric.from_dict({"name": "a", "weights": {"authenticity": 10.0}})
    breadth_heavy = Rubric.from_dict({"name": "b", "weights": {"breadth": 10.0}})

    assert (
        score_candidate(dossier, authenticity_heavy).score
        < score_candidate(dossier, breadth_heavy).score
    )


def test_to_dict_always_carries_band_coverage_and_the_dimension_detail():
    payload = score_candidate(make_dossier(), RUBRIC).to_dict()

    for key in (
        "handle",
        "score",
        "band",
        "confidence",
        "coverage",
        "dimensions",
        "unmeasured",
    ):
        assert key in payload
    assert payload["is_decision"] is False

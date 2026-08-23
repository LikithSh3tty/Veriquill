"""A dimension either cites evidence or reports itself unmeasured."""

from __future__ import annotations

import pytest

from veriquill.rank.dimensions import score_dimensions
from veriquill.rank.models import DimensionScore
from veriquill.rubric import DIMENSIONS


def make_dossier(**overrides):
    dossier = {
        "handle": "octocat",
        "red_flag_register": [],
        "code_quality_snapshot": [
            {"repository": "octocat/api", "checks": [], "authenticity_checks": []}
        ],
        "claim_vs_evidence": {
            "counts": {
                "corroborated": 0,
                "contradicted": 0,
                "unverifiable": 0,
                "undisclosed": 0,
            },
            "rows": [],
        },
        "analysis_coverage": {
            "repositories_considered": 1,
            "repositories_analysed": 1,
            "repositories_with_authored_code": 1,
            "repositories_deep_analysed": 1,
            "claims_total": 0,
            "claims_resolved": 0,
        },
    }
    dossier.update(overrides)
    return dossier


def flag(check_id, severity="high", confidence=1.0, flag_id="f1"):
    return {
        "flag_id": flag_id,
        "check_id": check_id,
        "severity": severity,
        "title": check_id,
        "rationale": "because",
        "confidence": confidence,
        "evidence": [{"repo": "octocat/api", "detail": "line 4"}],
    }


def by_name(dossier, dismissed=frozenset()):
    return {s.dimension: s for s in score_dimensions(dossier, dismissed)}


def test_every_dimension_is_scored_exactly_once():
    scores = score_dimensions(make_dossier())

    assert tuple(s.dimension for s in scores) == DIMENSIONS


def test_a_clean_candidate_scores_full_authenticity_and_cites_the_repositories():
    score = by_name(make_dossier())["authenticity"]

    assert score.score == pytest.approx(1.0)
    assert score.coverage == pytest.approx(1.0)
    assert score.evidence


def test_a_provenance_flag_lowers_authenticity():
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump")])

    score = by_name(dossier)["authenticity"]

    assert score.score < 1.0
    assert score.evidence[0].repo == "octocat/api"


def test_a_more_severe_flag_lowers_the_score_further():
    high = by_name(make_dossier(red_flag_register=[flag("provenance.bulk_dump", "high")]))
    critical = by_name(
        make_dossier(red_flag_register=[flag("provenance.bulk_dump", "critical")])
    )

    assert critical["authenticity"].score < high["authenticity"].score


def test_a_dismissed_flag_stops_counting_against_the_candidate():
    dossier = make_dossier(red_flag_register=[flag("provenance.bulk_dump", flag_id="abc")])

    kept = by_name(dossier)["authenticity"].score
    dropped = by_name(dossier, frozenset({"abc"}))["authenticity"].score

    assert dropped > kept
    assert dropped == pytest.approx(1.0)


def test_no_repository_analysed_means_authenticity_is_unmeasured():
    dossier = make_dossier(
        code_quality_snapshot=[],
        analysis_coverage={
            "repositories_considered": 2,
            "repositories_analysed": 0,
            "repositories_with_authored_code": 0,
            "repositories_deep_analysed": 0,
            "claims_total": 0,
            "claims_resolved": 0,
        },
    )

    score = by_name(dossier)["authenticity"]

    assert score.coverage == 0.0
    assert score.score is None
    assert "not" in score.basis.lower()


def test_a_candidate_writing_no_python_is_unmeasured_not_penalised():
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

    scores = by_name(dossier)

    for dimension in ("code_quality", "test_quality", "security"):
        assert scores[dimension].score is None
        assert scores[dimension].coverage == 0.0


def test_code_quality_and_test_quality_react_to_their_own_checks_only():
    dossier = make_dossier(red_flag_register=[flag("codeeval.no_tests")])

    scores = by_name(dossier)

    assert scores["test_quality"].score < 1.0
    assert scores["code_quality"].score == pytest.approx(1.0)


def test_security_reads_the_bandit_namespace():
    dossier = make_dossier(red_flag_register=[flag("codeeval.security.b602")])

    assert by_name(dossier)["security"].score < 1.0


def test_contradicted_claims_hurt_corroboration_more_than_corroborated_help():
    counts = {"corroborated": 1, "contradicted": 1, "unverifiable": 0, "undisclosed": 0}
    dossier = make_dossier(
        claim_vs_evidence={
            "counts": counts,
            "rows": [{"claim": "led auth", "repositories": ["octocat/api"]}],
        },
        analysis_coverage={
            "repositories_considered": 1,
            "repositories_analysed": 1,
            "repositories_with_authored_code": 1,
            "repositories_deep_analysed": 1,
            "claims_total": 2,
            "claims_resolved": 2,
        },
    )

    score = by_name(dossier)["claim_corroboration"]

    assert score.score == pytest.approx(0.0)
    assert score.coverage == pytest.approx(1.0)


def test_unverifiable_claims_lower_coverage_not_score():
    counts = {"corroborated": 1, "contradicted": 0, "unverifiable": 3, "undisclosed": 0}
    dossier = make_dossier(
        claim_vs_evidence={
            "counts": counts,
            "rows": [{"claim": "led auth", "repositories": ["octocat/api"]}],
        },
        analysis_coverage={
            "repositories_considered": 1,
            "repositories_analysed": 1,
            "repositories_with_authored_code": 1,
            "repositories_deep_analysed": 1,
            "claims_total": 4,
            "claims_resolved": 1,
        },
    )

    score = by_name(dossier)["claim_corroboration"]

    assert score.score == pytest.approx(1.0)
    assert score.coverage == pytest.approx(0.25)


def test_no_claims_at_all_is_unmeasured():
    score = by_name(make_dossier())["claim_corroboration"]

    assert score.score is None
    assert score.coverage == 0.0


def test_breadth_rises_with_repositories_that_hold_authored_code():
    def breadth(count):
        return by_name(
            make_dossier(
                code_quality_snapshot=[
                    {"repository": f"octocat/r{i}", "checks": [], "authenticity_checks": []}
                    for i in range(count)
                ],
                analysis_coverage={
                    "repositories_considered": count,
                    "repositories_analysed": count,
                    "repositories_with_authored_code": count,
                    "repositories_deep_analysed": count,
                    "claims_total": 0,
                    "claims_resolved": 0,
                },
            )
        )["breadth"].score

    assert breadth(1) < breadth(3) < breadth(5)
    assert breadth(9) == pytest.approx(1.0)


def test_a_measured_dimension_cannot_be_built_without_evidence():
    with pytest.raises(ValueError, match="evidence"):
        DimensionScore(
            dimension="security", score=1.0, coverage=1.0, evidence=(), basis="none"
        )


def test_an_unmeasured_dimension_cannot_carry_a_score():
    with pytest.raises(ValueError, match="unmeasured"):
        DimensionScore(
            dimension="security", score=0.5, coverage=0.0, evidence=(), basis="none"
        )


# --- coverage means the same thing in every dimension ----------------------


def _partial(considered: int, analysed: int) -> dict:
    """A dossier for an account read most-relevant-first."""
    return {
        "handle": "alice",
        "analysis_coverage": {
            "repositories_considered": considered,
            "repositories_analysed": analysed,
            "repositories_with_authored_code": analysed,
            "repositories_deep_analysed": analysed,
            "claims_total": 0,
            "claims_resolved": 0,
        },
        "red_flag_register": [],
        "code_quality_snapshot": [{"repository": f"alice/r{i}"} for i in range(analysed)],
    }


def test_a_partial_read_lowers_coverage_in_every_dimension():
    """Four of five used to report full coverage over a quarter of an account.

    A narrow band over thin evidence is what makes two candidates look
    separated when the evidence does not separate them.
    """
    scored = {d.dimension: d for d in score_dimensions(_partial(21, 5))}

    for name in ("authenticity", "code_quality", "test_quality", "security", "breadth"):
        assert scored[name].coverage == pytest.approx(5 / 21), name


def test_a_full_read_still_reports_full_coverage():
    scored = {d.dimension: d for d in score_dimensions(_partial(5, 5))}

    for dimension in scored.values():
        if dimension.measured:
            assert dimension.coverage == 1.0, dimension.dimension


def test_a_partial_read_widens_the_band_without_touching_the_score():
    """The rule the whole design rests on: thin evidence never lowers a score."""
    from veriquill.rank.score import score_candidate
    from veriquill.rubric import Rubric

    rubric = Rubric.from_dict({"name": "r"})
    full = score_candidate(_partial(5, 5), rubric)
    partial = score_candidate(_partial(21, 5), rubric)

    assert partial.score == full.score
    assert partial.width > full.width
    assert partial.confidence == "low"
    assert full.confidence == "high"


def test_nothing_cloned_leaves_every_repository_dimension_unmeasured():
    scored = {d.dimension: d for d in score_dimensions(_partial(21, 0))}

    for name in ("authenticity", "code_quality", "test_quality", "security", "breadth"):
        assert not scored[name].measured, name
        assert scored[name].score is None, name

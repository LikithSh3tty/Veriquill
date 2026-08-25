"""A bias audit that only works when someone hands you protected data is no
audit at all for the common case, so both paths are exercised here."""

from __future__ import annotations

import pytest

from tests.test_dimensions import flag, make_dossier
from veriquill.fairness.audit import FOUR_FIFTHS, audit_comparison, impact_ratio
from veriquill.rank.compare import compare
from veriquill.rubric import DIMENSIONS, Rubric

RUBRIC = Rubric.from_dict({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})


def dossier_for(handle, **overrides):
    payload = make_dossier(**overrides)
    payload["handle"] = handle
    return payload


def flagged(handle):
    return dossier_for(handle, red_flag_register=[flag("provenance.bulk_dump", "critical")])


def thin(handle):
    """A candidate almost nothing could be measured on."""
    return dossier_for(
        handle,
        analysis_coverage={
            "repositories_considered": 4,
            "repositories_analysed": 1,
            "repositories_with_authored_code": 1,
            "repositories_deep_analysed": 0,
            "claims_total": 0,
            "claims_resolved": 0,
        },
    )


def test_impact_ratio_is_one_when_selection_rates_match():
    assert impact_ratio(0.5, 0.5) == pytest.approx(1.0)


def test_impact_ratio_is_the_smaller_rate_over_the_larger():
    assert impact_ratio(0.2, 0.5) == pytest.approx(0.4)
    assert impact_ratio(0.5, 0.2) == pytest.approx(0.4)


def test_impact_ratio_is_undefined_when_nobody_was_selected():
    assert impact_ratio(0.0, 0.0) is None


def test_an_unlabelled_cohort_still_gets_a_coverage_audit():
    result = compare([dossier_for("a"), thin("b")], RUBRIC)

    report = audit_comparison(result)

    assert report["groups_supplied"] is False
    assert report["coverage"]["lowest"]["handle"] == "b"
    assert report["coverage"]["spread"] > 0
    assert report["selection"] == []


def test_an_unlabelled_audit_warns_when_coverage_is_uneven():
    result = compare([dossier_for("a"), thin("b")], RUBRIC)

    report = audit_comparison(result)

    assert any("coverage" in note.lower() for note in report["notes"])


def test_a_labelled_cohort_reports_selection_rates_per_group():
    result = compare(
        [dossier_for("a1"), dossier_for("a2"), flagged("b1"), flagged("b2")], RUBRIC
    )

    report = audit_comparison(
        result, groups={"a1": "A", "a2": "A", "b1": "B", "b2": "B"}, top_k=2
    )

    rates = {row["group"]: row["selection_rate"] for row in report["selection"]}
    assert rates["A"] == pytest.approx(1.0)
    assert rates["B"] == pytest.approx(0.0)
    assert report["groups_supplied"] is True


def test_a_disparate_selection_rate_fails_the_four_fifths_rule():
    result = compare(
        [dossier_for("a1"), dossier_for("a2"), flagged("b1"), flagged("b2")], RUBRIC
    )

    report = audit_comparison(
        result, groups={"a1": "A", "a2": "A", "b1": "B", "b2": "B"}, top_k=2
    )

    assert report["impact_ratio"] is not None
    assert report["impact_ratio"] < FOUR_FIFTHS
    assert report["passes_four_fifths"] is False


def test_an_even_cohort_passes_the_four_fifths_rule():
    result = compare(
        [dossier_for("a1"), flagged("a2"), dossier_for("b1"), flagged("b2")], RUBRIC
    )

    report = audit_comparison(
        result, groups={"a1": "A", "a2": "A", "b1": "B", "b2": "B"}, top_k=2
    )

    assert report["passes_four_fifths"] is True


def test_flag_rates_are_reported_per_check_and_per_group():
    clean, marked = dossier_for("a1"), flagged("b1")
    result = compare([clean, marked], RUBRIC)

    report = audit_comparison(
        result,
        groups={"a1": "A", "b1": "B"},
        top_k=1,
        dossiers={"a1": clean, "b1": marked},
    )

    rates = {
        (row["check_id"], row["group"]): row["rate"] for row in report["flag_rates"]
    }
    assert rates[("provenance.bulk_dump", "B")] == pytest.approx(1.0)
    assert rates[("provenance.bulk_dump", "A")] == pytest.approx(0.0)


def test_a_group_with_one_member_is_reported_as_too_small_to_audit():
    result = compare([dossier_for("a1"), dossier_for("a2"), flagged("b1")], RUBRIC)

    report = audit_comparison(
        result, groups={"a1": "A", "a2": "A", "b1": "B"}, top_k=1
    )

    assert any("small" in note.lower() for note in report["notes"])
    # And no verdict, because a rate over one candidate is 0% or 100% whatever
    # the tool did. A pass there is false comfort and a failure a false alarm.
    assert report["passes_four_fifths"] is None
    assert report["impact_ratio"] is not None


def test_the_audit_never_infers_a_group_it_was_not_given():
    result = compare([dossier_for("a1"), dossier_for("b1")], RUBRIC)

    report = audit_comparison(result, groups={"a1": "A"}, top_k=1)

    assert report["unlabelled_candidates"] == ["b1"]
    assert all(row["group"] != "unknown" for row in report["selection"])


def test_the_audit_states_that_it_is_not_a_legal_certification():
    report = audit_comparison(compare([dossier_for("a")], RUBRIC))

    assert "not" in report["disclaimer"].lower()
    assert "audit" in report["disclaimer"].lower()


def test_a_real_cohort_still_gets_a_verdict():
    """Withholding on thin data must not withhold on adequate data."""
    dossiers = [dossier_for(f"a{i}") for i in range(4)] + [dossier_for(f"b{i}") for i in range(4)]
    groups = {**{f"a{i}": "A" for i in range(4)}, **{f"b{i}": "B" for i in range(4)}}

    report = audit_comparison(compare(dossiers, RUBRIC), groups=groups, top_k=4)

    assert report["passes_four_fifths"] is not None


def test_a_one_member_group_cannot_raise_a_false_alarm_either():
    """The withheld verdict cuts both ways: no false pass, no false failure."""
    result = compare([dossier_for("a1"), dossier_for("a2"), flagged("b1")], RUBRIC)

    report = audit_comparison(result, groups={"a1": "A", "a2": "A", "b1": "B"}, top_k=2)

    assert report["passes_four_fifths"] is None


def test_the_rates_are_still_reported_when_the_verdict_is_withheld():
    """Describing the cohort is useful even when measuring it is not."""
    result = compare([dossier_for("a1"), dossier_for("a2"), flagged("b1")], RUBRIC)

    report = audit_comparison(result, groups={"a1": "A", "a2": "A", "b1": "B"}, top_k=1)

    assert {row["group"] for row in report["selection"]} == {"A", "B"}

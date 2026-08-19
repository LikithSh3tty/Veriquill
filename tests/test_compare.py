"""Ordering is a claim about candidates and needs the same care as a flag."""

from __future__ import annotations

from tests.test_dimensions import flag, make_dossier
from veriquill.rank.compare import compare
from veriquill.rubric import DIMENSIONS, Rubric

RUBRIC = Rubric.from_dict({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})


def dossier_for(handle, **overrides):
    dossier = make_dossier(**overrides)
    dossier["handle"] = handle
    return dossier


def test_a_cleaner_candidate_outranks_a_flagged_one():
    clean = dossier_for("clean")
    flagged = dossier_for(
        "flagged", red_flag_register=[flag("provenance.bulk_dump", "critical")]
    )

    result = compare([flagged, clean], RUBRIC)

    assert [row["handle"] for row in result["ranked"]] == ["clean", "flagged"]
    assert result["ranked"][0]["rank"] == 1


def test_every_candidate_gets_a_distinct_rank():
    """A recruiter needs an order to work down, not a set of equals.

    Overlapping bands mean the evidence separates two people weakly. That is
    worth saying, but it is not a reason to refuse to say who is ahead.
    """
    result = compare([dossier_for("a"), dossier_for("b"), dossier_for("c")], RUBRIC)

    ranks = [row["rank"] for row in result["ranked"]]
    assert ranks == [1, 2, 3]


def test_a_weak_separation_is_reported_without_collapsing_the_order():
    result = compare([dossier_for("a"), dossier_for("b")], RUBRIC)

    rows = result["ranked"]
    assert rows[0]["rank"] == 1 and rows[1]["rank"] == 2
    assert rows[1]["separated_weakly"] is True
    assert "overlap" in rows[1]["separation_note"].lower()


def test_a_clear_gap_is_not_called_weak():
    flagged = dossier_for(
        "flagged", red_flag_register=[flag("provenance.bulk_dump", "critical")]
    )

    result = compare([dossier_for("a"), flagged], RUBRIC)

    assert result["ranked"][1]["separated_weakly"] is False


def test_the_order_is_deterministic_when_scores_are_identical():
    first = compare([dossier_for("b"), dossier_for("a")], RUBRIC)
    second = compare([dossier_for("a"), dossier_for("b")], RUBRIC)

    assert [r["handle"] for r in first["ranked"]] == [r["handle"] for r in second["ranked"]]


def test_an_unscorable_candidate_is_unranked_not_last():
    blank = dossier_for(
        "blank",
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

    result = compare([dossier_for("a"), blank], RUBRIC)

    assert [row["handle"] for row in result["ranked"]] == ["a"]
    assert result["unranked"][0]["handle"] == "blank"
    assert result["unranked"][0]["reason"]


def test_scores_are_absolute_so_adding_a_candidate_never_moves_another_score():
    alone = compare([dossier_for("a")], RUBRIC)
    crowded = compare([dossier_for("a"), dossier_for("b"), dossier_for("c")], RUBRIC)

    assert alone["ranked"][0]["score"]["score"] == crowded["ranked"][0]["score"]["score"]


def test_each_row_cites_the_dimensions_that_moved_it():
    flagged = dossier_for(
        "flagged", red_flag_register=[flag("provenance.bulk_dump", "critical")]
    )

    result = compare([dossier_for("a"), flagged], RUBRIC)

    row = next(r for r in result["ranked"] if r["handle"] == "flagged")
    assert any("authenticity" in driver for driver in row["drivers"])


def test_dismissed_flags_are_applied_per_candidate():
    flagged = dossier_for(
        "flagged",
        red_flag_register=[flag("provenance.bulk_dump", "critical", flag_id="abc")],
    )

    before = compare([flagged], RUBRIC)
    after = compare([flagged], RUBRIC, {"flagged": frozenset({"abc"})})

    assert after["ranked"][0]["score"]["score"] > before["ranked"][0]["score"]["score"]


def test_output_states_it_is_not_a_decision():
    result = compare([dossier_for("a")], RUBRIC)

    assert "decision" in result["disclaimer"].lower()


def test_ordering_is_stable_for_identical_input():
    dossiers = [dossier_for("a"), dossier_for("b"), dossier_for("c")]

    assert compare(dossiers, RUBRIC) == compare(dossiers, RUBRIC)

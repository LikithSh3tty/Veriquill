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


def test_indistinguishable_candidates_share_a_tie_group_and_a_rank():
    result = compare([dossier_for("a"), dossier_for("b")], RUBRIC)

    ranks = {row["handle"]: row["rank"] for row in result["ranked"]}
    groups = {row["tie_group"] for row in result["ranked"]}
    assert ranks["a"] == ranks["b"] == 1
    assert len(groups) == 1


def test_a_candidate_after_a_tie_gets_competition_ranking():
    flagged = dossier_for(
        "flagged", red_flag_register=[flag("provenance.bulk_dump", "critical")]
    )

    result = compare([dossier_for("a"), dossier_for("b"), flagged], RUBRIC)

    ranks = {row["handle"]: row["rank"] for row in result["ranked"]}
    assert ranks["a"] == ranks["b"] == 1
    assert ranks["flagged"] == 3


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

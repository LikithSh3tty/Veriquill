"""Stored analysis is evidence; it is written once and never edited."""

from __future__ import annotations

import pytest

from tests.test_dimensions import make_dossier
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.rubric import DIMENSIONS, Rubric
from veriquill.store import (
    StoreError,
    create_comparison,
    dossier_payloads,
    get_comparison,
    latest_dossier,
    list_rubrics,
    load_rubric,
    save_dossier,
    save_rubric,
)

RUBRIC = Rubric.from_dict({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})


@pytest.fixture()
def session(tmp_path):
    engine = make_engine(tmp_path / "veriquill.sqlite")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as active:
        yield active


def dossier_for(handle):
    payload = make_dossier()
    payload["handle"] = handle
    return payload


def test_a_rubric_round_trips(session):
    save_rubric(session, RUBRIC)

    assert load_rubric(session, "backend") == RUBRIC


def test_saving_a_rubric_twice_keeps_the_newest_version(session):
    save_rubric(session, RUBRIC)
    save_rubric(
        session,
        Rubric.from_dict({"name": "backend", "version": 2, "weights": {"security": 1.0}}),
    )

    assert load_rubric(session, "backend").version == 2
    assert [r.name for r in list_rubrics(session)] == ["backend"]


def test_loading_an_unknown_rubric_names_it(session):
    with pytest.raises(StoreError, match="backend"):
        load_rubric(session, "backend")


def test_a_dossier_is_stored_with_a_content_hash(session):
    record = save_dossier(session, dossier_for("octocat"))

    assert record.candidate_handle == "octocat"
    assert len(record.payload_hash) == 64


def test_identical_dossiers_hash_identically(session):
    first = save_dossier(session, dossier_for("octocat"))
    second = save_dossier(session, dossier_for("octocat"))

    assert first.payload_hash == second.payload_hash
    assert latest_dossier(session, "octocat").id == second.id


def test_a_dossier_without_a_handle_is_refused(session):
    with pytest.raises(StoreError, match="handle"):
        save_dossier(session, {"red_flag_register": []})


def test_a_comparison_stores_one_entry_per_candidate_with_its_machine_score(session):
    save_rubric(session, RUBRIC)
    save_dossier(session, dossier_for("a"))
    save_dossier(session, dossier_for("b"))

    comparison = create_comparison(session, "backend", ["a", "b"])

    assert comparison.status == "pending_review"
    assert comparison.revision == 0
    assert {entry.candidate_handle for entry in comparison.entries} == {"a", "b"}
    assert all(entry.machine_score["score"] is not None for entry in comparison.entries)
    assert sorted(entry.machine_rank for entry in comparison.entries) == [1, 2]


def test_a_comparison_needs_a_stored_dossier_for_every_candidate(session):
    save_rubric(session, RUBRIC)
    save_dossier(session, dossier_for("a"))

    with pytest.raises(StoreError, match="ghost"):
        create_comparison(session, "backend", ["a", "ghost"])


def test_a_comparison_needs_at_least_one_candidate(session):
    save_rubric(session, RUBRIC)

    with pytest.raises(StoreError, match="candidate"):
        create_comparison(session, "backend", [])


def test_comparisons_are_retrievable_by_id_and_carry_their_dossiers(session):
    save_rubric(session, RUBRIC)
    save_dossier(session, dossier_for("a"))
    comparison = create_comparison(session, "backend", ["a"])

    fetched = get_comparison(session, comparison.id)

    assert fetched.id == comparison.id
    assert [payload["handle"] for payload in dossier_payloads(session, fetched)] == ["a"]


def test_fetching_an_unknown_comparison_is_refused(session):
    with pytest.raises(StoreError, match="not found"):
        get_comparison(session, 999)

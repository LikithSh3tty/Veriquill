"""The gate exists so that no ranking leaves the building unseen by a human."""

from __future__ import annotations

import pytest

from tests.test_dimensions import flag, make_dossier
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.models import ReviewAction
from veriquill.review import (
    ReviewError,
    approve,
    audit_log,
    dismissed_by_handle,
    effective_result,
    export_payload,
    record_action,
)
from veriquill.rubric import DIMENSIONS, Rubric
from veriquill.store import create_comparison, save_dossier, save_rubric

RUBRIC = Rubric.from_dict({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})


@pytest.fixture()
def session(tmp_path):
    engine = make_engine(tmp_path / "veriquill.sqlite")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as active:
        yield active


def seed(session, handles=("flagged",)):
    save_rubric(session, RUBRIC)
    for handle in handles:
        payload = make_dossier(
            red_flag_register=[flag("provenance.bulk_dump", "critical", flag_id="abc")]
        )
        payload["handle"] = handle
        save_dossier(session, payload)
    return create_comparison(session, "backend", list(handles))


def test_a_new_comparison_is_pending_review(session):
    comparison = seed(session)

    assert comparison.status == "pending_review"


def test_export_is_refused_while_pending(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="pending"):
        export_payload(session, comparison)


def test_export_names_what_is_outstanding(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="approve"):
        export_payload(session, comparison)


def test_approval_opens_the_gate(session):
    comparison = seed(session)

    approve(session, comparison, "reviewer@example.com")

    assert comparison.status == "reviewed"
    payload = export_payload(session, comparison)
    assert payload["status"] == "reviewed"


def test_an_action_without_a_reason_is_refused(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="reason"):
        record_action(
            session,
            comparison,
            actor="reviewer",
            action="flag_dismiss",
            candidate="flagged",
            target="abc",
            reason="   ",
        )


def test_an_action_without_an_actor_is_refused(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="actor"):
        record_action(
            session,
            comparison,
            actor="",
            action="flag_dismiss",
            candidate="flagged",
            target="abc",
            reason="false positive",
        )


def test_dismissing_an_unknown_flag_is_refused_and_echoes_the_id(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="zzz"):
        record_action(
            session,
            comparison,
            actor="reviewer",
            action="flag_dismiss",
            candidate="flagged",
            target="zzz",
            reason="false positive",
        )


def test_an_action_for_a_candidate_outside_the_comparison_is_refused(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="stranger"):
        record_action(
            session,
            comparison,
            actor="reviewer",
            action="flag_dismiss",
            candidate="stranger",
            target="abc",
            reason="false positive",
        )


def test_an_unknown_action_is_refused(session):
    comparison = seed(session)

    with pytest.raises(ReviewError, match="teleport"):
        record_action(
            session,
            comparison,
            actor="reviewer",
            action="teleport",
            candidate="flagged",
            target="abc",
            reason="why not",
        )


def test_a_dismissal_raises_the_effective_score_without_touching_the_machine_score(session):
    comparison = seed(session)
    before = [dict(entry.machine_score) for entry in comparison.entries]

    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="employer-owned import, verified in interview",
    )

    result = effective_result(session, comparison)
    machine = before[0]["score"]
    effective = result["ranked"][0]["score"]["score"]

    assert effective > machine
    assert [dict(entry.machine_score) for entry in comparison.entries] == before


def test_confirming_a_flag_leaves_the_score_alone(session):
    comparison = seed(session)
    baseline = effective_result(session, comparison)["ranked"][0]["score"]["score"]

    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_confirm",
        candidate="flagged",
        target="abc",
        reason="checked the history, it holds",
    )

    assert effective_result(session, comparison)["ranked"][0]["score"]["score"] == baseline


def test_dismissed_flags_are_reported_per_candidate(session):
    comparison = seed(session, ("flagged", "other"))
    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="false positive",
    )

    dismissed = dismissed_by_handle(session, comparison)

    assert dismissed["flagged"] == frozenset({"abc"})
    assert dismissed.get("other", frozenset()) == frozenset()


def test_a_band_override_is_shown_next_to_the_machine_band(session):
    comparison = seed(session)
    approve(session, comparison, "reviewer")

    record_action(
        session,
        comparison,
        actor="reviewer",
        action="band_override",
        candidate="flagged",
        target="strong hire",
        reason="context from a reference call",
    )
    approve(session, comparison, "reviewer")

    payload = export_payload(session, comparison)
    row = payload["ranked"][0]

    assert row["human_band"] == "strong hire"
    assert row["score"]["band"]
    assert row["override_reason"] == "context from a reference call"


def test_an_action_after_approval_reopens_the_gate_and_bumps_the_revision(session):
    comparison = seed(session)
    approve(session, comparison, "reviewer")

    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="second look",
    )

    assert comparison.status == "pending_review"
    assert comparison.revision == 1
    with pytest.raises(ReviewError, match="pending"):
        export_payload(session, comparison)


def test_the_audit_log_is_ordered_and_complete(session):
    comparison = seed(session)
    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="false positive",
    )
    approve(session, comparison, "manager")

    log = audit_log(session, comparison)

    assert [row["action"] for row in log] == ["flag_dismiss", "approve"]
    assert log[0]["actor"] == "reviewer"
    assert log[0]["reason"] == "false positive"
    assert all(row["created_at"] for row in log)


def test_no_review_action_is_ever_updated_or_deleted(session):
    comparison = seed(session)
    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="false positive",
    )
    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_confirm",
        candidate="flagged",
        target="abc",
        reason="changed my mind",
    )

    assert session.query(ReviewAction).count() == 2


def test_a_confirmation_after_a_dismissal_reinstates_the_flag(session):
    comparison = seed(session)
    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_dismiss",
        candidate="flagged",
        target="abc",
        reason="false positive",
    )
    lifted = effective_result(session, comparison)["ranked"][0]["score"]["score"]

    record_action(
        session,
        comparison,
        actor="reviewer",
        action="flag_confirm",
        candidate="flagged",
        target="abc",
        reason="changed my mind",
    )

    assert effective_result(session, comparison)["ranked"][0]["score"]["score"] < lifted


def test_the_export_carries_the_audit_log_and_says_it_is_not_a_decision(session):
    comparison = seed(session)
    approve(session, comparison, "reviewer")

    payload = export_payload(session, comparison)

    assert payload["audit_log"]
    assert "decision" in payload["disclaimer"].lower()

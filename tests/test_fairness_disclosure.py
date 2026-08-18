"""The compliance pack has to describe the tool that actually shipped."""

from __future__ import annotations

from veriquill.fairness.disclosure import build_disclosure, render_markdown
from veriquill.rubric import DIMENSIONS


def test_the_disclosure_lists_every_dimension_that_can_affect_a_ranking():
    disclosure = build_disclosure()

    measured = {row["dimension"] for row in disclosure["what_is_measured"]}
    assert measured == set(DIMENSIONS)


def test_every_measured_dimension_says_what_evidence_it_rests_on():
    for row in build_disclosure()["what_is_measured"]:
        assert row["evidence"], f"{row['dimension']} does not say what it reads"


def test_the_disclosure_names_the_attributes_that_are_removed():
    excluded = build_disclosure()["what_is_excluded"]

    categories = {row["category"] for row in excluded}
    assert {"date_of_birth", "gender", "religion", "health", "nationality"} <= categories


def test_the_excluded_list_is_generated_from_the_running_code():
    """A hand-written list would drift from the scanner the day someone edits it."""
    from veriquill.fairness.signals import CATEGORIES

    excluded = {row["category"] for row in build_disclosure()["what_is_excluded"]}
    assert excluded == set(CATEGORIES)


def test_the_disclosure_states_the_human_gate_and_the_audit_log():
    oversight = build_disclosure()["human_oversight"]

    text = " ".join(oversight).lower()
    assert "approve" in text
    assert "audit" in text


def test_the_disclosure_states_the_limits_the_specification_forbids_crossing():
    limits = " ".join(build_disclosure()["hard_limits"]).lower()

    assert "never" in limits
    assert "reject" in limits


def test_the_disclosure_carries_the_tool_version():
    from veriquill import __version__

    assert build_disclosure()["tool_version"] == __version__


def test_an_audit_result_is_carried_through_when_one_is_supplied():
    disclosure = build_disclosure(audit={"impact_ratio": 0.9, "passes_four_fifths": True})

    assert disclosure["bias_audit"]["impact_ratio"] == 0.9


def test_without_an_audit_the_pack_says_none_was_run_rather_than_implying_a_pass():
    disclosure = build_disclosure()

    assert disclosure["bias_audit"] is None
    assert any("no bias audit" in note.lower() for note in disclosure["notes"])


def test_the_markdown_rendering_is_readable_and_complete():
    markdown = render_markdown(build_disclosure())

    assert markdown.startswith("# ")
    for heading in ("What is measured", "What is excluded", "Human oversight", "Hard limits"):
        assert heading in markdown
    for dimension in DIMENSIONS:
        assert dimension in markdown

"""Turning a job description into a rubric.

A recruiter has a job description, not a weights table. Deriving the weights from
the text keeps the rubric honest — every weight cites the phrase that raised it,
so a candidate can be told why security counted for a third of the score.

No model is involved. A weighting nobody can trace is exactly the thing this
tool exists to refuse.
"""

from __future__ import annotations

import pytest

from veriquill.jobspec import derive_rubric, read_job_description
from veriquill.rubric import DIMENSIONS


def test_an_empty_description_is_refused():
    with pytest.raises(ValueError, match="empty"):
        derive_rubric("senior-backend", "   ")


def test_a_description_with_no_signal_falls_back_to_the_defaults():
    spec = read_job_description("We are hiring a person to join our team.")

    assert spec.emphases == {}
    assert "no phrase" in spec.note.lower()


def test_testing_language_raises_the_test_dimension():
    spec = read_job_description(
        "You will write unit tests and practise test-driven development."
    )

    assert "test_quality" in spec.emphases
    assert any("test" in phrase.lower() for phrase in spec.emphases["test_quality"])


def test_security_language_raises_the_security_dimension():
    spec = read_job_description("Experience with OWASP and secure coding is required.")

    assert "security" in spec.emphases


def test_ownership_language_raises_authenticity():
    spec = read_job_description("You will own services end to end and ship them yourself.")

    assert "authenticity" in spec.emphases


def test_maintainability_language_raises_code_quality():
    spec = read_job_description("We care about clean, maintainable code and refactoring.")

    assert "code_quality" in spec.emphases


def test_a_weighted_rubric_still_sums_to_one():
    rubric = derive_rubric("secure-backend", "OWASP, secure coding, threat modelling.")

    assert sum(rubric.weights.values()) == pytest.approx(1.0)
    assert set(rubric.weights) == set(DIMENSIONS)


def test_the_emphasised_dimension_outweighs_its_default():
    from veriquill.rubric import DEFAULT_WEIGHTS

    rubric = derive_rubric("secure-backend", "Security, OWASP, secure coding, vulnerabilities.")

    assert rubric.weights["security"] > DEFAULT_WEIGHTS["security"]


def test_two_emphases_both_rise():
    rubric = derive_rubric(
        "quality-backend", "You will write unit tests. Secure coding matters here."
    )

    from veriquill.rubric import DEFAULT_WEIGHTS

    assert rubric.weights["test_quality"] > DEFAULT_WEIGHTS["test_quality"]
    assert rubric.weights["security"] > DEFAULT_WEIGHTS["security"]


def test_every_emphasis_cites_the_phrase_that_caused_it():
    spec = read_job_description("Security is critical. We practise TDD.")

    for dimension, phrases in spec.emphases.items():
        assert phrases, f"{dimension} was raised with nothing to point at"


def test_the_derivation_is_reported_for_a_human_to_check():
    spec = read_job_description("Security is critical. We practise TDD.")
    report = spec.to_dict()

    assert report["emphases"]["security"]
    assert report["note"]


def test_matching_is_case_insensitive_and_ignores_word_fragments():
    spec = read_job_description("SECURITY matters.")
    assert "security" in spec.emphases

    # "insecurity" in prose about job insecurity should not weight the rubric.
    unrelated = read_job_description("There is no job insecurity here.")
    assert "security" not in unrelated.emphases


def test_the_same_description_always_derives_the_same_rubric():
    text = "We need tests, security, and clean code."

    assert derive_rubric("r", text).weights == derive_rubric("r", text).weights


def test_boilerplate_ownership_prose_does_not_raise_authenticity():
    """Almost every posting says these. None of them describe how work was authored."""
    for boilerplate in (
        "We own our roadmap and we move fast.",
        "Join a leading fintech company.",
        "Your team lead will mentor you through onboarding.",
        "This role led to two promotions last year.",
        "We own the problem, not the solution.",
    ):
        spec = read_job_description(boilerplate)
        assert "authenticity" not in spec.emphases, boilerplate


def test_authorship_prose_still_raises_authenticity():
    for genuine in (
        "You will be the sole author of the billing service.",
        "Greenfield work: you build this from scratch.",
        "You will own services end to end.",
        "We expect you to work independently.",
        "You led the migration yourself.",
    ):
        spec = read_job_description(genuine)
        assert "authenticity" in spec.emphases, genuine

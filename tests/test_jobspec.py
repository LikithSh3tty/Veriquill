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


def test_modern_testing_vocabulary_raises_the_test_dimension():
    for posting in (
        "You will write pytest suites for our services.",
        "We use Jest and Playwright.",
        "Every merge runs the CI pipeline.",
        "We hold a code coverage threshold.",
        "Strong test automation experience.",
        "You will write regression tests.",
    ):
        spec = read_job_description(posting)
        assert "test_quality" in spec.emphases, posting


def test_modern_security_vocabulary_raises_the_security_dimension():
    for posting in (
        "You will run SAST across the monorepo.",
        "Experience triaging CVEs.",
        "We care about dependency scanning and supply chain security.",
        "You will handle secrets management and encryption.",
        "System hardening is part of the role.",
    ):
        spec = read_job_description(posting)
        assert "security" in spec.emphases, posting


def test_the_longer_phrase_wins_an_overlap():
    """"end-to-end tests" is about testing. It must not also read as authorship."""
    spec = read_job_description("You will write end-to-end tests for every release.")

    assert "test_quality" in spec.emphases
    assert "authenticity" not in spec.emphases


def test_an_overlap_does_not_swallow_a_separate_mention():
    spec = read_job_description(
        "You will write end-to-end tests, and you own the service end to end."
    )

    assert "test_quality" in spec.emphases
    assert "authenticity" in spec.emphases


def test_a_negated_phrase_does_not_raise_its_dimension():
    for posting in (
        "We don't do heavy testing here.",
        "There is no formal QA process.",
        "We do not run penetration testing.",
        "This role involves minimal test automation.",
        "We ship without unit tests.",
        "We never write integration tests.",
    ):
        spec = read_job_description(posting)
        assert "test_quality" not in spec.emphases or "security" in spec.emphases, posting
        assert "test_quality" not in spec.emphases, posting


def test_a_negation_stops_at_the_clause_it_belongs_to():
    spec = read_job_description(
        "There is no formal QA process, but you will write unit tests yourself."
    )

    assert "test_quality" in spec.emphases
    assert "unit tests" in spec.emphases["test_quality"]


def test_a_negation_does_not_reach_across_a_sentence():
    spec = read_job_description("We have no legacy code. You will write unit tests.")

    assert "test_quality" in spec.emphases


def test_a_negated_phrase_is_reported_rather_than_silently_dropped():
    spec = read_job_description("We don't do heavy testing here.")

    assert "test_quality" in spec.negated
    assert spec.to_dict()["negated"]["test_quality"]
    assert "negated" in spec.note.lower() or "read as negated" in spec.note.lower()


def test_a_positive_description_reports_no_negations():
    spec = read_job_description("You will write unit tests and practise TDD.")

    assert spec.negated == {}


def test_second_person_ownership_still_raises_authenticity():
    """Trimming bare "own" and "lead" must not cost the phrasing that meant it.

    "We own our roadmap" is boilerplate about the company. "You will own the
    payments service" is a statement about who writes the code, which is the
    thing authenticity measures.
    """
    for genuine in (
        "You will own the payments service.",
        "You'll own this from design through to production.",
        "You will lead the rewrite.",
        "We expect you to own and operate what you build.",
    ):
        spec = read_job_description(genuine)
        assert "authenticity" in spec.emphases, genuine


def test_first_person_company_boilerplate_still_does_not():
    for boilerplate in (
        "We own our roadmap and we move fast.",
        "We own the problem, not the solution.",
        "Join a leading fintech company.",
        "Our team owns its own priorities.",
    ):
        spec = read_job_description(boilerplate)
        assert "authenticity" not in spec.emphases, boilerplate

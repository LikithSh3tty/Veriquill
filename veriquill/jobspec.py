"""Deriving a rubric from a job description.

A recruiter has a job description, not a weights table. This reads the
description and raises the dimensions it actually asks for, recording the phrase
behind every change — so a candidate can be told that security carried a third of
the score because the posting said "OWASP" and "secure coding", not because a
model felt strongly about it.

No language model touches this. A weighting nobody can trace back to the words
that produced it is the thing this tool exists to refuse, and a ranking path that
changes when a model is retrained is not reproducible.

The mapping is deliberately small and readable. It is better to raise nothing and
fall back to the defaults than to guess at intent from vocabulary that does not
clearly belong to a dimension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from veriquill.rubric import DEFAULT_WEIGHTS, Rubric

# How much one matched phrase raises a dimension, before normalisation.
EMPHASIS_STEP = 0.12
MAX_STEPS = 3

# Phrases that clearly belong to one dimension. Matched on word boundaries, so
# "insecurity" never counts as "security".
SIGNALS: dict[str, tuple[str, ...]] = {
    "test_quality": (
        "unit test",
        "unit tests",
        "integration test",
        "integration tests",
        "regression test",
        "regression tests",
        "smoke test",
        "smoke tests",
        "contract test",
        "contract tests",
        "end-to-end test",
        "end-to-end tests",
        "end to end test",
        "end to end tests",
        "e2e",
        "test-driven",
        "test driven",
        "tdd",
        "test coverage",
        "code coverage",
        "coverage threshold",
        "coverage gate",
        "test automation",
        "automated test",
        "automated tests",
        "test suite",
        "test suites",
        "testing",
        "tests",
        "qa",
        "pytest",
        "jest",
        "vitest",
        "junit",
        "rspec",
        "mocha",
        "cypress",
        "playwright",
        "selenium",
        "continuous integration",
        "ci pipeline",
        "ci/cd",
        "property-based testing",
    ),
    "security": (
        "security",
        "secure coding",
        "owasp",
        "vulnerability",
        "vulnerabilities",
        "threat model",
        "threat modelling",
        "threat modeling",
        "penetration testing",
        "pen testing",
        "pentest",
        "pentesting",
        "appsec",
        "sast",
        "dast",
        "cve",
        "cves",
        "dependency scanning",
        "code scanning",
        "supply chain security",
        "secrets management",
        "encryption",
        "cryptography",
        "hardening",
        "least privilege",
        "security review",
        "security reviews",
        "authentication",
        "authorisation",
        "authorization",
    ),
    # Every phrase here has to describe how work was *authored*. Bare "own",
    # "lead", and "led" did not: "we own our roadmap", "a leading fintech
    # company", and "your team lead will mentor you" are boilerplate that
    # appears in most postings, and they were raising authenticity for nearly
    # every job. A phrase that fires on filler is worse than no phrase at all,
    # because the weight it moves cannot be defended to the candidate.
    "authenticity": (
        "ownership",
        "take ownership",
        "end to end",
        "end-to-end",
        "from scratch",
        "from the ground up",
        "greenfield",
        "sole author",
        "sole developer",
        "sole engineer",
        "sole maintainer",
        "independently",
        "led the",
        "ship it yourself",
        "build it yourself",
    ),
    "code_quality": (
        "clean code",
        "maintainable",
        "maintainability",
        "refactor",
        "refactoring",
        "readable",
        "readability",
        "code quality",
        "code review",
        "code reviews",
        "architecture",
        "design patterns",
        "technical debt",
        "separation of concerns",
        "modularity",
        "static analysis",
        "linting",
        "type safety",
        "legacy code",
    ),
    "breadth": (
        "full stack",
        "full-stack",
        "generalist",
        "variety of projects",
        "range of technologies",
        "polyglot",
        "wear many hats",
        "across the stack",
        "multiple languages",
        "several languages",
        "broad experience",
    ),
    "claim_corroboration": (
        "portfolio",
        "references",
        "verifiable",
        "demonstrated experience",
        "proven track record",
        "open source contributions",
        "public repositories",
        "code samples",
        "work samples",
        "github profile",
    ),
}


@dataclass(frozen=True, slots=True)
class JobSpec:
    """What a job description asked for, and the words it asked with."""

    text: str
    emphases: dict[str, list[str]] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "emphases": {k: list(v) for k, v in self.emphases.items()},
            "note": self.note,
        }


def _matches(haystack: str) -> list[tuple[int, int, str, str]]:
    """Every phrase occurrence in the text, as (start, end, dimension, phrase)."""
    found: list[tuple[int, int, str, str]] = []
    for dimension, phrases in SIGNALS.items():
        for phrase in phrases:
            pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
            for match in re.finditer(pattern, haystack):
                found.append((match.start(), match.end(), dimension, phrase))
    return found


def _resolve_overlaps(
    matches: list[tuple[int, int, str, str]],
) -> list[tuple[int, int, str, str]]:
    """Where two phrases cover the same words, the longer one wins.

    "end-to-end tests" is a sentence about testing. Read phrase by phrase it is
    also the authenticity phrase "end-to-end", and both dimensions used to rise
    off the same four words. Longest-match-first settles it the way a reader
    would: the more specific phrase is the one the posting meant.

    Ties break on dimension name so the result never depends on dict order.
    """
    kept: list[tuple[int, int, str, str]] = []
    for start, end, dimension, phrase in sorted(
        matches, key=lambda m: (-(m[1] - m[0]), m[0], m[2])
    ):
        if any(start < other_end and other_start < end for other_start, other_end, _, _ in kept):
            continue
        kept.append((start, end, dimension, phrase))
    return kept


def read_job_description(text: str) -> JobSpec:
    """Find the phrases that name a dimension, and record where each one came from."""
    haystack = (text or "").lower()
    emphases: dict[str, list[str]] = {}

    for _start, _end, dimension, phrase in sorted(_resolve_overlaps(_matches(haystack))):
        phrases = emphases.setdefault(dimension, [])
        if phrase not in phrases:
            phrases.append(phrase)

    if emphases:
        named = ", ".join(sorted(emphases))
        note = (
            f"Weights were raised for {named} because the description asks for them. "
            "Every other dimension keeps its default weight."
        )
    else:
        note = (
            "No phrase in this description named a dimension, so the default "
            "weights apply unchanged. Edit the weights directly if the posting "
            "means something the wording does not say."
        )

    return JobSpec(text=text, emphases=emphases, note=note)


def derive_rubric(name: str, text: str) -> Rubric:
    """Turn a job description into a rubric, weights normalised as usual."""
    if not (text or "").strip():
        raise ValueError("the job description is empty; nothing can be derived from it")

    spec = read_job_description(text)
    weights = dict(DEFAULT_WEIGHTS)

    for dimension, phrases in spec.emphases.items():
        # More mentions mean more emphasis, but only up to a point: a posting
        # that says "test" six times does not want the other five dimensions
        # to vanish.
        steps = min(len(phrases), MAX_STEPS)
        weights[dimension] = weights[dimension] + EMPHASIS_STEP * steps

    return Rubric.from_dict({"name": name, "weights": weights})

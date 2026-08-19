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
        "test-driven",
        "test driven",
        "tdd",
        "test coverage",
        "testing",
        "tests",
        "qa",
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
        "appsec",
    ),
    "authenticity": (
        "own",
        "owns",
        "ownership",
        "end to end",
        "end-to-end",
        "from scratch",
        "sole author",
        "independently",
        "self-starter",
        "lead",
        "led",
    ),
    "code_quality": (
        "clean code",
        "maintainable",
        "maintainability",
        "refactor",
        "refactoring",
        "readable",
        "code quality",
        "architecture",
        "design patterns",
        "technical debt",
    ),
    "breadth": (
        "full stack",
        "full-stack",
        "generalist",
        "variety of projects",
        "range of technologies",
        "polyglot",
    ),
    "claim_corroboration": (
        "portfolio",
        "references",
        "verifiable",
        "demonstrated experience",
        "proven track record",
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


def read_job_description(text: str) -> JobSpec:
    """Find the phrases that name a dimension, and record where each one came from."""
    haystack = (text or "").lower()
    emphases: dict[str, list[str]] = {}

    for dimension, phrases in SIGNALS.items():
        found = [
            phrase
            for phrase in phrases
            if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack)
        ]
        if found:
            emphases[dimension] = found

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

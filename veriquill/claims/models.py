"""Claims are what a candidate says about themselves.

A claim is never a fact. It is a statement the candidate made, carried
together with the exact text it came from, so the reconciliation layer can
later ask whether the evidence supports it. The provenance requirement is
enforced here rather than left to convention, mirroring the evidence
requirement on `Finding`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClaimKind(StrEnum):
    ROLE = "role"
    SKILL = "skill"
    PROJECT = "project"
    EDUCATION = "education"
    ACHIEVEMENT = "achievement"
    ENDORSEMENT = "endorsement"


@dataclass(frozen=True, slots=True)
class ClaimSource:
    """Where a claim was stated, precisely enough to quote back."""

    document: str
    locator: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class Claim:
    kind: ClaimKind
    text: str
    source: ClaimSource
    subject: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.source.excerpt.strip():
            raise ValueError(
                f"claim {self.text!r} has an empty excerpt; a claim must quote "
                "the text it was drawn from"
            )
        if not self.source.locator.strip():
            raise ValueError(
                f"claim {self.text!r} has no locator; a claim must say where in "
                "the document it was stated"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"claim {self.text!r} has confidence {self.confidence}, which is "
                "outside [0.0, 1.0]"
            )

    def describe(self) -> str:
        """The specification's phrasing: candidate states X, source: Y."""
        return f"candidate states {self.text!r}, source: {self.source.document} {self.source.locator}"

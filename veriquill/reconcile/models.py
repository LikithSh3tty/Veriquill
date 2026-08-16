"""The four ways a claim can stand against the evidence (specification §7)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from veriquill.claims.models import Claim
from veriquill.reconcile.evidence import RepoEvidence


class Verdict(StrEnum):
    CONTRADICTED = "contradicted"
    CORROBORATED = "corroborated"
    UNDISCLOSED = "undisclosed"
    UNVERIFIABLE = "unverifiable"

    @property
    def rank(self) -> int:
        """Sort key: the most decisive result a recruiter should read first."""
        return _ORDER[self]


_ORDER = {
    Verdict.CONTRADICTED: 0,
    Verdict.CORROBORATED: 1,
    Verdict.UNDISCLOSED: 2,
    Verdict.UNVERIFIABLE: 3,
}


@dataclass(frozen=True, slots=True)
class Reconciliation:
    verdict: Verdict
    rationale: str
    confidence: float
    claim: Claim | None = None
    evidence: tuple[RepoEvidence, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict is Verdict.UNDISCLOSED:
            if not self.evidence:
                raise ValueError("an undisclosed strength must cite the work it found")
        elif self.claim is None:
            raise ValueError(f"a {self.verdict} result must carry the claim it judged")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} is outside [0.0, 1.0]")

    @property
    def counts_for(self) -> bool:
        """Whether this should weigh in the candidate's favour."""
        return self.verdict in (Verdict.CORROBORATED, Verdict.UNDISCLOSED)

    @property
    def counts_against(self) -> bool:
        """Only a contradiction weighs against.

        Absence of evidence is never negative evidence: an unverifiable claim
        is noted and then left alone.
        """
        return self.verdict is Verdict.CONTRADICTED

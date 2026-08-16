"""Findings are the only output type of every Veriquill check.

A finding is advisory. It never asserts wrongdoing and never carries a verdict.
It cannot exist without at least one piece of evidence, which is enforced here
rather than left to convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Sort key: 0 is most severe."""
        return _SEVERITY_ORDER[self]


_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A pointer to the artifact that produced a finding."""

    repo: str
    path: str | None = None
    line: int | None = None
    commit_sha: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    check_id: str
    severity: Severity
    title: str
    rationale: str
    confidence: float
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(
                f"finding {self.check_id!r} has no evidence; "
                "every finding must cite at least one artifact"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"finding {self.check_id!r} has confidence {self.confidence}, "
                "which is outside [0.0, 1.0]"
            )

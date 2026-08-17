"""What a score is allowed to look like.

Two invariants are enforced here rather than left to convention, for the same
reason `Finding` enforces its own: a score that cites nothing is an opinion, and
a dimension nobody could measure must not carry a number that reads as a
judgment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veriquill.findings import EvidenceRef


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension: str
    score: float | None
    coverage: float
    evidence: tuple[EvidenceRef, ...]
    basis: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError(
                f"{self.dimension} has coverage {self.coverage}, outside [0.0, 1.0]"
            )
        if self.coverage == 0.0 and self.score is not None:
            raise ValueError(
                f"{self.dimension} is unmeasured but carries a score; an unmeasured "
                "dimension has no number"
            )
        if self.coverage > 0.0:
            if self.score is None:
                raise ValueError(f"{self.dimension} has coverage but no score")
            if not 0.0 <= self.score <= 1.0:
                raise ValueError(
                    f"{self.dimension} has score {self.score}, outside [0.0, 1.0]"
                )
            if not self.evidence:
                raise ValueError(
                    f"{self.dimension} was scored without evidence; every scored "
                    "dimension must cite at least one artifact"
                )

    @property
    def measured(self) -> bool:
        return self.coverage > 0.0 and self.score is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "coverage": self.coverage,
            "basis": self.basis,
            "evidence": [
                {
                    "repo": ref.repo,
                    "path": ref.path,
                    "line": ref.line,
                    "commit_sha": ref.commit_sha,
                    "detail": ref.detail,
                }
                for ref in self.evidence
            ],
        }


@dataclass(frozen=True, slots=True)
class CandidateScore:
    handle: str
    score: float | None
    band: tuple[float, float]
    width: float
    confidence: str
    coverage: float
    dimensions: tuple[DimensionScore, ...]
    unmeasured: tuple[str, ...]
    bar_breaches: tuple[str, ...]

    @property
    def scored(self) -> bool:
        return self.score is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "score": self.score,
            "band": list(self.band),
            "width": self.width,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "unmeasured": list(self.unmeasured),
            "bar_breaches": list(self.bar_breaches),
            "is_decision": False,
        }

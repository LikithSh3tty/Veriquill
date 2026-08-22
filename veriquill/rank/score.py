"""Aggregate the dimensions into one confidence-qualified number.

The number is never presented alone. It travels with the band that reflects how
much of the portfolio could be read, the dimensions that could not be measured,
and the reason each one could not. A candidate with three private repositories
has to read as "we could not tell", never as "weak".
"""

from __future__ import annotations

from typing import Any

from veriquill.rank.dimensions import score_dimensions
from veriquill.rank.models import CandidateScore, DimensionScore
from veriquill.rubric import Rubric

BAND_FLOOR = 0.05
BAND_SPAN = 0.25

HIGH_CONFIDENCE_COVERAGE = 0.75
MODERATE_CONFIDENCE_COVERAGE = 0.40


def _confidence(coverage: float) -> str:
    if coverage >= HIGH_CONFIDENCE_COVERAGE:
        return "high"
    if coverage >= MODERATE_CONFIDENCE_COVERAGE:
        return "moderate"
    return "low"


def _unscored(
    handle: str, dimensions: tuple[DimensionScore, ...], unmeasured: tuple[str, ...]
) -> CandidateScore:
    return CandidateScore(
        handle=handle,
        score=None,
        band=(0.0, 1.0),
        width=0.5,
        confidence="low",
        coverage=0.0,
        dimensions=dimensions,
        unmeasured=unmeasured,
        bar_breaches=(),
    )


def score_candidate(
    dossier: dict[str, Any], rubric: Rubric, dismissed: frozenset[str] = frozenset()
) -> CandidateScore:
    handle = str(dossier.get("handle") or "unknown")
    dimensions = score_dimensions(dossier, dismissed, rubric)

    measured = [
        d for d in dimensions if d.measured and rubric.weights.get(d.dimension, 0.0) > 0
    ]
    measured_names = {d.dimension for d in measured}
    unmeasured = tuple(d.dimension for d in dimensions if d.dimension not in measured_names)

    if not measured:
        return _unscored(handle, dimensions, unmeasured)

    total_weight = sum(rubric.weights[d.dimension] for d in measured)
    normalised = {d.dimension: rubric.weights[d.dimension] / total_weight for d in measured}

    score = sum(normalised[d.dimension] * float(d.score) for d in measured)
    coverage = sum(normalised[d.dimension] * d.coverage for d in measured)
    width = BAND_FLOOR + BAND_SPAN * (1.0 - coverage)

    breaches = tuple(
        d.dimension
        for d in measured
        if d.dimension in rubric.minimum_bars
        and float(d.score) < rubric.minimum_bars[d.dimension]
    )

    return CandidateScore(
        handle=handle,
        score=round(score, 6),
        band=(round(max(0.0, score - width), 6), round(min(1.0, score + width), 6)),
        width=round(width, 6),
        confidence=_confidence(coverage),
        coverage=round(coverage, 6),
        dimensions=dimensions,
        unmeasured=unmeasured,
        bar_breaches=breaches,
    )

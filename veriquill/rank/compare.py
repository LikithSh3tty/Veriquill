"""Order a cohort without pretending to more precision than the evidence has.

Two candidates whose scores sit inside each other's confidence bands are a tie,
and are reported as one. A candidate nobody could score is reported as unranked
with the reason, rather than placed at the bottom where a reader would take the
position for a judgment.

Scoring is absolute, never cohort-relative: adding a candidate changes who is
above whom, never anyone's score. An audited comparison stays reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from veriquill.rank.models import CandidateScore
from veriquill.rank.score import score_candidate
from veriquill.rubric import Rubric

DISCLAIMER = (
    "This ordering is advisory and is not a hiring decision. Scores are "
    "confidence-qualified: a wide band reflects how little evidence was available, "
    "not a judgment about the candidate."
)

MAX_DRIVERS = 3


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    handle: str
    rank: int
    tie_group: int
    score: CandidateScore
    drivers: tuple[str, ...]
    separated_weakly: bool = False
    separation_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "rank": self.rank,
            "tie_group": self.tie_group,
            "score": self.score.to_dict(),
            "drivers": list(self.drivers),
            "separated_weakly": self.separated_weakly,
            "separation_note": self.separation_note,
        }


def _medians(scores: list[CandidateScore]) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for candidate in scores:
        for dimension in candidate.dimensions:
            if dimension.measured:
                values.setdefault(dimension.dimension, []).append(float(dimension.score))
    return {name: median(numbers) for name, numbers in values.items()}


def _drivers(candidate: CandidateScore, medians: dict[str, float]) -> tuple[str, ...]:
    deltas = []
    for dimension in candidate.dimensions:
        if not dimension.measured or dimension.dimension not in medians:
            continue
        delta = float(dimension.score) - medians[dimension.dimension]
        deltas.append((abs(delta), dimension.dimension, delta))

    deltas.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        f"{name} {delta:+.2f} against the cohort median"
        for _, name, delta in deltas[:MAX_DRIVERS]
    )


def compare(
    dossiers: list[dict[str, Any]],
    rubric: Rubric,
    dismissed_by_handle: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    dismissals = dismissed_by_handle or {}
    scored: list[CandidateScore] = []
    unranked: list[dict[str, Any]] = []

    for dossier in dossiers:
        handle = str(dossier.get("handle") or "unknown")
        candidate = score_candidate(dossier, rubric, dismissals.get(handle, frozenset()))
        if candidate.scored:
            scored.append(candidate)
        else:
            unranked.append(
                {
                    "handle": handle,
                    "reason": (
                        "no dimension could be measured: "
                        + "; ".join(d.basis for d in candidate.dimensions if not d.measured)
                    ),
                    "score": candidate.to_dict(),
                }
            )

    scored.sort(key=lambda c: (-float(c.score), c.handle))
    medians = _medians(scored)

    rows: list[ComparisonRow] = []
    tie_group = 0
    for index, candidate in enumerate(scored):
        weakly = False
        note = ""

        if index > 0:
            previous = scored[index - 1]
            gap = float(previous.score) - float(candidate.score)
            if gap < min(previous.width, candidate.width):
                weakly = True
                note = (
                    f"Bands overlap with {previous.handle}: {gap:.2f} apart, which is "
                    "inside the range the evidence leaves open. The order is real but "
                    "thin, and worth confirming by reading both."
                )
            else:
                tie_group += 1
        rows.append(
            ComparisonRow(
                handle=candidate.handle,
                # Every candidate gets their own place. A recruiter needs a list to
                # work down; overlapping bands are a caveat on a position, not a
                # reason to refuse to give one.
                rank=index + 1,
                tie_group=tie_group,
                score=candidate,
                drivers=_drivers(candidate, medians),
                separated_weakly=weakly,
                separation_note=note,
            )
        )

    return {
        "rubric": rubric.to_dict(),
        "ranked": [row.to_dict() for row in rows],
        "unranked": sorted(unranked, key=lambda row: row["handle"]),
        "disclaimer": DISCLAIMER,
    }

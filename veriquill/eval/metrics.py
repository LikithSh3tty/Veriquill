"""Scoring the checks against hand-labelled ground truth (specification §10).

Precision is the number that matters here. A false positive is an accusation
against a real person, so the harness reports precision and recall separately
and never blends them into a single headline figure.

Calibration answers a different question: when a finding says it is 80%
confident, is it right about 80% of the time? A confident-but-wrong check is
worse than an uncertain one, because a recruiter has no way to discount it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CheckScore:
    check_id: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        """Of the times this check fired, how often was it right?"""
        fired = self.true_positives + self.false_positives
        return self.true_positives / fired if fired else 0.0

    @property
    def recall(self) -> float:
        """Of the cases that should have fired, how many did?"""
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 0.0

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def score_checks(
    cases: Sequence[tuple[set[str], set[str]]],
) -> dict[str, CheckScore]:
    """Score every check across cases of `(fired_check_ids, expected_check_ids)`."""
    tallies: dict[str, list[int]] = {}

    for fired, expected in cases:
        for check in fired | expected:
            counts = tallies.setdefault(check, [0, 0, 0])
            if check in fired and check in expected:
                counts[0] += 1
            elif check in fired:
                counts[1] += 1
            else:
                counts[2] += 1

    return {
        check: CheckScore(
            check_id=check,
            true_positives=counts[0],
            false_positives=counts[1],
            false_negatives=counts[2],
        )
        for check, counts in sorted(tallies.items())
    }


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_confidence: float
    observed_accuracy: float

    @property
    def gap(self) -> float:
        """Claimed confidence minus earned accuracy; positive is overconfident."""
        return self.mean_confidence - self.observed_accuracy

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": [round(self.lower, 2), round(self.upper, 2)],
            "count": self.count,
            "mean_confidence": round(self.mean_confidence, 4),
            "observed_accuracy": round(self.observed_accuracy, 4),
            "gap": round(self.gap, 4),
        }


def calibration_bins(
    observations: Iterable[tuple[float, bool]], bin_count: int = 5
) -> list[CalibrationBin]:
    """Bucket `(confidence, was_correct)` pairs and compare claim to outcome."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]

    for confidence, correct in observations:
        clamped = min(max(confidence, 0.0), 1.0)
        index = min(int(clamped * bin_count), bin_count - 1)
        buckets[index].append((clamped, correct))

    bins: list[CalibrationBin] = []
    width = 1.0 / bin_count

    for index, bucket in enumerate(buckets):
        lower, upper = index * width, (index + 1) * width
        if not bucket:
            bins.append(CalibrationBin(lower, upper, 0, 0.0, 0.0))
            continue
        mean_confidence = sum(c for c, _ in bucket) / len(bucket)
        accuracy = sum(1 for _, ok in bucket if ok) / len(bucket)
        bins.append(
            CalibrationBin(lower, upper, len(bucket), mean_confidence, accuracy)
        )

    return bins

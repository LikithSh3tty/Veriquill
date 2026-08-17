"""The recruiter rubric.

Veriquill fixes the dimensions and lets the recruiter set their weights. The
dimensions are fixed because each one is backed by a check that emits evidence;
a dimension nobody can evidence would be an opinion with a number attached.

A rubric that cannot be trusted refuses to load. Silently rescaling nonsense
would produce a ranking nobody could defend afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DIMENSIONS: tuple[str, ...] = (
    "authenticity",
    "code_quality",
    "claim_corroboration",
    "test_quality",
    "security",
    "breadth",
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "authenticity": 0.30,
    "code_quality": 0.20,
    "claim_corroboration": 0.20,
    "test_quality": 0.15,
    "security": 0.10,
    "breadth": 0.05,
}


class RubricError(ValueError):
    """Raised when a rubric cannot be trusted to score anyone."""


def _check_dimensions(names: Any, field: str) -> dict[str, float]:
    if names is None:
        return {}
    if not isinstance(names, dict):
        raise RubricError(f"{field} must be an object mapping dimension to number")

    unknown = sorted(set(names) - set(DIMENSIONS))
    if unknown:
        raise RubricError(
            f"{field} names unknown dimension(s): {', '.join(unknown)}; "
            f"known dimensions are {', '.join(DIMENSIONS)}"
        )

    values: dict[str, float] = {}
    for dimension, value in names.items():
        try:
            values[dimension] = float(value)
        except (TypeError, ValueError):
            raise RubricError(f"{field}[{dimension}] is not a number") from None
    return values


@dataclass(frozen=True, slots=True)
class Rubric:
    name: str
    version: int
    weights: dict[str, float]
    minimum_bars: dict[str, float]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Rubric:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise RubricError("rubric needs a name")

        supplied = _check_dimensions(payload.get("weights"), "weights")
        for dimension, value in supplied.items():
            if value < 0:
                raise RubricError(f"weight for {dimension} is negative")

        weights = dict(DEFAULT_WEIGHTS)
        weights.update(supplied)

        total = sum(weights.values())
        if total <= 0:
            raise RubricError("weights sum to zero; nothing could be scored")
        weights = {dimension: value / total for dimension, value in weights.items()}

        bars = _check_dimensions(payload.get("minimum_bars"), "minimum_bars")
        for dimension, value in bars.items():
            if not 0.0 <= value <= 1.0:
                raise RubricError(
                    f"minimum bar for {dimension} is {value}; bars must be between 0 and 1"
                )

        return cls(
            name=name,
            version=int(payload.get("version", 1)),
            weights=weights,
            minimum_bars=bars,
        )

    @classmethod
    def load(cls, path: Path) -> Rubric:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RubricError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RubricError(f"{path} must contain a JSON object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "weights": dict(self.weights),
            "minimum_bars": dict(self.minimum_bars),
        }

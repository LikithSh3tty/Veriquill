"""The recruiter rubric.

Six dimensions ship with the tool, and a recruiter sets their weights. A team
that weighs something else can add a dimension of their own, but only by saying
which checks it scores from.

That condition is the whole design, not a formality. The original rule here was
that dimensions are fixed, because each one is backed by a check that emits
evidence and a dimension nobody can evidence is an opinion with a number
attached. Letting a rubric invent a dimension out of a name would have thrown
that away. Binding one to check ids keeps it: a custom dimension is scored from
findings that cite files and lines exactly like the built-in six, and one whose
checks never fired reports as unmeasured rather than quietly scoring zero.

A rubric that cannot be trusted refuses to load. Silently rescaling nonsense
would produce a ranking nobody could defend afterwards.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


_DIMENSION_NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class RubricError(ValueError):
    """Raised when a rubric cannot be trusted to score anyone."""


@dataclass(frozen=True, slots=True)
class CustomDimension:
    """A dimension a team added, and the checks it is allowed to read.

    `checks` are matched as prefixes, so `codeeval.security.` covers every
    security check while `codeeval.no_tests` names exactly one. Prefixes are
    what make this survive new checks being added later without the rubric
    having to be rewritten.
    """

    name: str
    checks: tuple[str, ...]
    description: str = ""

    def matches(self, check_id: str) -> bool:
        return any(check_id.startswith(prefix) for prefix in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"checks": list(self.checks), "description": self.description}


def _parse_custom(payload: Any) -> dict[str, CustomDimension]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise RubricError("custom_dimensions must be an object keyed by dimension name")

    custom: dict[str, CustomDimension] = {}
    for name, spec in payload.items():
        if name in DIMENSIONS:
            raise RubricError(
                f"{name} is a built-in dimension; give the custom one a different name "
                "rather than redefining what it reads"
            )
        if not _DIMENSION_NAME.match(str(name)):
            raise RubricError(
                f"{name!r} is not a usable dimension name: lower case, digits and "
                "underscores, starting with a letter, up to 40 characters"
            )
        if not isinstance(spec, dict):
            raise RubricError(f"custom_dimensions[{name}] must be an object")

        raw_checks = spec.get("checks")
        if not isinstance(raw_checks, list) or not raw_checks:
            raise RubricError(
                f"custom_dimensions[{name}] must list at least one check id in "
                "'checks'. A dimension that reads no check cannot cite evidence, "
                "and a score nobody can trace back to an artifact is an opinion"
            )
        checks = tuple(str(check).strip() for check in raw_checks)
        if any(not check for check in checks):
            raise RubricError(f"custom_dimensions[{name}] has an empty check id")

        custom[str(name)] = CustomDimension(
            name=str(name),
            checks=checks,
            description=str(spec.get("description") or "").strip(),
        )
    return custom


def _check_dimensions(names: Any, field: str, known: tuple[str, ...]) -> dict[str, float]:
    if names is None:
        return {}
    if not isinstance(names, dict):
        raise RubricError(f"{field} must be an object mapping dimension to number")

    unknown = sorted(set(names) - set(known))
    if unknown:
        raise RubricError(
            f"{field} names unknown dimension(s): {', '.join(unknown)}; "
            f"known dimensions are {', '.join(known)}"
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
    custom_dimensions: dict[str, CustomDimension] = field(default_factory=dict)

    @property
    def dimensions(self) -> tuple[str, ...]:
        """Every dimension this rubric scores, built-ins first then additions."""
        return DIMENSIONS + tuple(sorted(self.custom_dimensions))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Rubric:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise RubricError("rubric needs a name")

        custom = _parse_custom(payload.get("custom_dimensions"))
        known = DIMENSIONS + tuple(sorted(custom))

        supplied = _check_dimensions(payload.get("weights"), "weights", known)
        for dimension, value in supplied.items():
            if value < 0:
                raise RubricError(f"weight for {dimension} is negative")

        # A custom dimension carries no default: a team that adds one and never
        # weights it meant nothing by it, and silently inventing a weight would
        # move a ranking on a number nobody chose.
        unweighted = sorted(set(custom) - set(supplied))
        if unweighted:
            raise RubricError(
                f"custom dimension(s) {', '.join(unweighted)} have no weight; "
                "give each one a weight or remove it"
            )

        weights = dict(DEFAULT_WEIGHTS)
        weights.update(supplied)

        total = sum(weights.values())
        if total <= 0:
            raise RubricError("weights sum to zero; nothing could be scored")
        weights = {dimension: value / total for dimension, value in weights.items()}

        bars = _check_dimensions(payload.get("minimum_bars"), "minimum_bars", known)
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
            custom_dimensions=custom,
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
            "custom_dimensions": {
                name: spec.to_dict() for name, spec in sorted(self.custom_dimensions.items())
            },
        }

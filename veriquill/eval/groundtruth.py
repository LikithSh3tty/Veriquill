"""Hand-labelled cases the checks are measured against (specification §10).

Each case is a repository built to a known shape, with the checks that *should*
fire and the checks that must *not*. The forbidden set is the important half:
it is where false positives are caught, and a false positive here is a false
accusation against a real candidate.

These are synthetic. They measure whether a check does what it claims on a
shape we constructed, not whether the thresholds are right for real portfolios.
Labelling real profiles is the next step and is not done yet; the harness
reports that limitation rather than implying broader coverage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from veriquill.eval.fixtures import (
    CommitSpec,
    build_repo,
    bulk_dump_history,
    burst_history,
    organic_history,
)

CANDIDATE = ("candidate@example.com", "candidate")
_START = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class LabeledCase:
    name: str
    description: str
    build: Callable[[Path], Path]
    expected: frozenset[str] = frozenset()
    forbidden: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)
    identities: frozenset[str] = frozenset(CANDIDATE)


def _healthy(base: Path) -> Path:
    """Organic history, own work, has tests: nothing should fire."""
    specs = organic_history()
    specs.append(
        CommitSpec(
            message="add tests",
            files={
                "tests/test_module_0.py": (
                    "from src.module_0 import f0\n\n\ndef test_f0():\n    assert f0() == 0\n"
                )
            },
            when=_START + timedelta(days=20),
        )
    )
    return build_repo(base, "healthy", specs)


def _burst(base: Path) -> Path:
    return build_repo(base, "burst", burst_history())


def _bulk_dump(base: Path) -> Path:
    return build_repo(base, "bulk-dump", bulk_dump_history())


def _foreign(base: Path) -> Path:
    """Someone else authored every commit."""
    specs = [
        CommitSpec(
            message=f"upstream work {i}",
            files={f"src/core_{i}.py": "x = 1\n" * 60},
            when=_START + timedelta(days=i),
            author_name="Upstream Author",
            author_email="upstream@example.com",
        )
        for i in range(8)
    ]
    return build_repo(base, "foreign", specs)


def _vendored(base: Path) -> Path:
    """Mostly node_modules, a little authored code."""
    files = {f"node_modules/dep{i}/index.js": "z = 1\n" * 400 for i in range(8)}
    files["src/app.py"] = "def main():\n    return 1\n"
    return build_repo(
        base,
        "vendored",
        [CommitSpec(message="import deps", files=files, when=_START)],
    )


def _insecure(base: Path) -> Path:
    specs = organic_history()
    specs.append(
        CommitSpec(
            message="add config",
            files={"config.py": 'DB_PASSWORD = "hunter2supersecret"\n'},
            when=_START + timedelta(days=20),
        )
    )
    return build_repo(base, "insecure", specs)


def _trivial_tests(base: Path) -> Path:
    specs = organic_history()
    specs.append(
        CommitSpec(
            message="add tests",
            files={
                "tests/test_all.py": (
                    "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n"
                )
            },
            when=_START + timedelta(days=20),
        )
    )
    return build_repo(base, "trivial-tests", specs)


CASES: tuple[LabeledCase, ...] = (
    LabeledCase(
        name="healthy",
        description="Organic history, own commits, real tests. The control case.",
        build=_healthy,
        expected=frozenset(),
        forbidden=frozenset(
            {
                "provenance.cadence_burst",
                "provenance.bulk_dump",
                "provenance.fork_presented_as_original",
                "provenance.low_contribution",
                "provenance.template_inflation",
                "codeeval.no_tests",
                "codeeval.trivial_tests",
            }
        ),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="scripted-burst",
        description="Thirty commits inside one minute.",
        build=_burst,
        expected=frozenset({"codeeval.no_tests", "provenance.cadence_burst"}),
        forbidden=frozenset({"provenance.low_contribution"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="bulk-dump",
        description="Whole codebase in the first commit, then a README edit.",
        build=_bulk_dump,
        expected=frozenset({"codeeval.no_tests", "provenance.bulk_dump"}),
        forbidden=frozenset({"provenance.low_contribution"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="authored-by-another",
        description="Every commit belongs to a different author.",
        build=_foreign,
        expected=frozenset(
            {
                "codeeval.no_tests",
                "provenance.low_contribution",
                "provenance.fork_presented_as_original",
            }
        ),
        forbidden=frozenset({"provenance.cadence_burst"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="vendored-inflation",
        description="Reported size is almost entirely node_modules.",
        build=_vendored,
        expected=frozenset({"codeeval.no_tests", "provenance.template_inflation"}),
        forbidden=frozenset({"provenance.low_contribution"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="hardcoded-secret",
        description="An API-key literal committed in config.py.",
        build=_insecure,
        expected=frozenset({"codeeval.no_tests", "codeeval.security.b105"}),
        forbidden=frozenset({"provenance.cadence_burst", "provenance.bulk_dump"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="trivial-tests",
        description="Tests exist but every assertion is `assert True`.",
        build=_trivial_tests,
        expected=frozenset({"codeeval.trivial_tests"}),
        forbidden=frozenset({"codeeval.no_tests"}),
        metadata={"fork": False},
    ),
)

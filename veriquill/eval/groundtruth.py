"""Hand-labelled cases the checks are measured against (specification §10).

Each case is a repository built to a known shape, with the checks that *should*
fire and the checks that must *not*. The forbidden set is the important half:
it is where false positives are caught, and a false positive here is a false
accusation against a real candidate.

These are synthetic. They measure whether a check does what it claims on a
shape we constructed, not whether the thresholds are right for real portfolios.
Labelling real profiles is the next step and is not done yet; the harness
reports that limitation rather than implying broader coverage.

The forbidden half carries more weight than the expected half. Half of these
cases exist because the shape they describe once produced a finding it should
not have: a branch rebased before merging, a repository whose dependency bot
outcommitted its author, a suite written with unittest rather than pytest, a
Django layout whose entry points no import statement names. Each was a real
false positive against a real kind of candidate, and each is checked here by
reintroducing the fault and confirming the case fails.
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


# --- repositories that must stay silent ------------------------------------
#
# Every case below is a real shape that used to produce a finding it should not
# have. They measure precision, which is the half that matters here: a missed
# flag costs a recruiter a question, a false one can cost a candidate a job.

_BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


def _rebased(base: Path) -> Path:
    """Twenty days of work, rebased once before merging.

    Rebase rewrites every committer date to the moment it ran. Reading those
    instead of the author dates made an ordinary branch tidy-up look like a
    scripted push of finished work.
    """
    rebase_moment = _START + timedelta(days=60)
    specs = [
        CommitSpec(
            message=f"feature step {i}",
            files={f"src/step_{i}.py": f"def step_{i}():\n    return {i}\n"},
            when=_START + timedelta(days=i),
            committed=rebase_moment + timedelta(seconds=i),
        )
        for i in range(20)
    ]
    return build_repo(base, "rebased", specs)


def _bot_maintained(base: Path) -> Path:
    """The candidate wrote every human commit; a bot bumped dependencies."""
    specs = [
        CommitSpec(
            message=f"build the thing {i}",
            files={f"src/mod_{i}.py": f"def f{i}():\n    return {i}\n" * 20},
            when=_START + timedelta(days=i),
        )
        for i in range(10)
    ]
    specs += [
        CommitSpec(
            message=f"bump dependency {i}",
            files={"package-lock.json": f'{{"rev": {i}}}\n' * 400},
            when=_START + timedelta(days=20 + i),
            author_name=_BOT[0],
            author_email=_BOT[1],
        )
        for i in range(60)
    ]
    return build_repo(base, "bot-maintained", specs)


def _unittest_suite(base: Path) -> Path:
    """Real tests written with unittest, plus one smoke test.

    Counting only assert statements made self.assertEqual invisible, so the one
    `assert True` read as the whole suite.
    """
    cases = "".join(
        f"    def test_{i}(self):\n        self.assertEqual(add({i}, 1), {i + 1})\n"
        for i in range(12)
    )
    specs = [
        CommitSpec(
            message="add module",
            files={"src/calc.py": "def add(a, b):\n    return a + b\n"},
            when=_START + timedelta(days=1),
        ),
        CommitSpec(
            message="add tests",
            files={
                "tests/test_calc.py": (
                    "import unittest\n\nfrom src.calc import add\n\n\n"
                    "class CalcTest(unittest.TestCase):\n"
                    + cases
                    + "\n    def test_smoke(self):\n        assert True\n"
                )
            },
            when=_START + timedelta(days=4),
        ),
    ]
    return build_repo(base, "unittest-suite", specs)


def _framework_layout(base: Path) -> Path:
    """A Django project. Its entry points are reached by configuration.

    Also names a test file by the suffix convention, which the dead-module
    check used not to recognise.
    """
    # A well-formed project: every module is reached by an import somewhere.
    # What the check must not do is call the framework's own entry points dead
    # because no import statement names them.
    files = {
        "manage.py": "import os\n\n\ndef main():\n    return os.environ\n",
        "proj/__init__.py": "",
        "proj/settings.py": "DEBUG = False\n",
        "proj/urls.py": "from app import views\n\nurlpatterns = [views.index]\n",
        "proj/wsgi.py": "application = None\n",
        "proj/asgi.py": "application = None\n",
        "app/__init__.py": "",
        "app/apps.py": "from app import signals\n\n\ndef ready():\n    return signals\n",
        "app/models.py": "def build():\n    return 1\n",
        "app/serializers.py": "from app.models import build\n\n\ndef dump():\n    return build()\n",
        "app/services.py": "from app.serializers import dump\n\n\ndef run():\n    return dump()\n",
        "app/forms.py": "def clean():\n    return True\n",
        "app/signals.py": "def connect():\n    return None\n",
        "app/views.py": (
            "from app.forms import clean\n"
            "from app.services import run\n\n\n"
            "def index():\n    return run() and clean()\n"
        ),
        "app/helpers_test.py": (
            "from app.models import build\n\n\ndef test_build():\n    assert build() == 1\n"
        ),
    }
    ordered = list(files.items())
    specs = [
        CommitSpec(
            message=f"build out the project {i}",
            files=dict(ordered[i::3]),
            when=_START + timedelta(days=i * 3),
        )
        for i in range(3)
    ]
    return build_repo(base, "framework-layout", specs)


CASES: tuple[LabeledCase, ...] = (
    LabeledCase(
        name="rebased-branch",
        description=(
            "Twenty days of work rebased once before merging. Every committer "
            "date is identical; the author dates are not."
        ),
        build=_rebased,
        expected=frozenset(),
        forbidden=frozenset({"provenance.cadence_burst", "provenance.bulk_dump"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="bot-maintained",
        description=(
            "The candidate wrote every human commit. A dependency bot wrote four "
            "times as many, each rewriting a lockfile in full."
        ),
        build=_bot_maintained,
        expected=frozenset(),
        forbidden=frozenset(
            {
                "provenance.low_contribution",
                "provenance.template_inflation",
                "provenance.cadence_burst",
            }
        ),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="unittest-suite",
        description=(
            "Twelve real unittest cases and one smoke test. Assertions are calls "
            "here, not assert statements."
        ),
        build=_unittest_suite,
        expected=frozenset(),
        forbidden=frozenset({"codeeval.trivial_tests", "codeeval.no_tests"}),
        metadata={"fork": False},
    ),
    LabeledCase(
        name="framework-layout",
        description=(
            "A Django project whose entry points are reached by configuration, "
            "and a test file named by the suffix convention."
        ),
        build=_framework_layout,
        expected=frozenset(),
        forbidden=frozenset({"codeeval.unreferenced_modules", "codeeval.no_tests"}),
        metadata={"fork": False},
    ),
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
        description=(
            "Every commit belongs to a different author, on a repository GitHub "
            "reports as original."
        ),
        build=_foreign,
        expected=frozenset({"codeeval.no_tests", "provenance.low_contribution"}),
        # The label used to expect a fork flag here. It was wrong: nothing in the
        # evidence establishes an upstream author when GitHub says the repository
        # is not a fork, and the accusation lands hardest on candidates who simply
        # renamed their account or commit under a different git identity.
        forbidden=frozenset(
            {"provenance.cadence_burst", "provenance.fork_presented_as_original"}
        ),
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


@dataclass(frozen=True, slots=True)
class ReferenceCohort:
    """A set of cases with human orderings of them, best first.

    `orders` holds one ordering per rater. Two raters who disagree are more
    useful than one who does not: the disagreement is what sets the ceiling the
    tool is measured against.
    """

    name: str
    description: str
    members: tuple[str, ...]
    orders: tuple[tuple[str, ...], ...]


# These orderings are the project's own judgment about its own synthetic cases.
# They are not an independent expert panel, and the harness says so in its
# limitations rather than letting a correlation figure imply otherwise. The two
# orderings differ on one genuinely arguable pair: a committed secret in
# otherwise organic work, versus a repository whose size is mostly vendored.
REFERENCE_COHORTS: tuple[ReferenceCohort, ...] = (
    ReferenceCohort(
        name="synthetic-spread",
        description=(
            "Every labelled case ranked against the others, from clean organic "
            "work down to a repository the candidate did not author."
        ),
        members=(
            "healthy",
            "trivial-tests",
            "hardcoded-secret",
            "vendored-inflation",
            "scripted-burst",
            "bulk-dump",
            "authored-by-another",
        ),
        orders=(
            (
                "healthy",
                "trivial-tests",
                "hardcoded-secret",
                "vendored-inflation",
                "scripted-burst",
                "bulk-dump",
                "authored-by-another",
            ),
            (
                "healthy",
                "trivial-tests",
                "vendored-inflation",
                "hardcoded-secret",
                "scripted-burst",
                "bulk-dump",
                "authored-by-another",
            ),
        ),
    ),
)

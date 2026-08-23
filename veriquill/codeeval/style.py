"""Lint compliance, via ruff.

Ruff runs isolated from the repository's own configuration. Without that, a
candidate who ships a `pyproject.toml` selecting no rules reports zero lint
violations: eighty-one became none in a repository built to test exactly
that. A tool whose purpose is noticing a portfolio arranged to look good
cannot hand the candidate the ruler.

Isolation is also the fairer reading. Two candidates with identical code and
different lint configurations were being scored differently, and the one
holding themselves to a stricter standard came off worse for it.

Files are named explicitly rather than the repository root being recursed,
so vendored and generated trees stay out of a metric that is supposed to
describe what the candidate wrote.
"""

from __future__ import annotations

from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.codeeval.runner import python_tool, run_json
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

VIOLATIONS_PER_KLOC_THRESHOLD = 20.0


def _relative(filename: str, root: Path) -> str:
    try:
        return Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(filename).name


def check_style(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    if not profile.python_files or profile.total_loc == 0:
        return []

    reports = run_json(
        python_tool(
            "ruff",
            "check",
            # Ignore any configuration the repository ships, so every candidate
            # is measured against the same rules rather than against their own.
            "--isolated",
            "--output-format",
            "json",
            "--no-cache",
        ),
        profile.python_files,
        settings.analyser_timeout_seconds,
    )
    violations = [v for report in reports for v in (report or [])]

    if not violations:
        return []

    per_kloc = len(violations) / max(profile.total_loc / 1000, 0.001)
    if per_kloc < VIOLATIONS_PER_KLOC_THRESHOLD:
        return []

    return [
        Finding(
            check_id="codeeval.lint_debt",
            severity=Severity.LOW,
            title="Lint compliance is weak",
            rationale=(
                f"{len(violations)} lint violations across roughly {profile.total_loc} "
                f"lines ({per_kloc:.0f} per thousand lines). Style is a weak signal on "
                "its own and says nothing about correctness."
            ),
            confidence=0.7,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=_relative(v["filename"], profile.root),
                    line=(v.get("location") or {}).get("row"),
                    detail=f"{v.get('code')}: {v.get('message')}"[:200],
                )
                for v in violations[:5]
            ),
        )
    ]

"""Template and dependency inflation.

Reported repository size counts vendored trees. Authored size does not.

Only commits a person wrote are measured. A dependency bot rewrites a
lockfile in full on every bump, so sixty bumps count that lockfile sixty
times: a candidate with three thousand lines of genuine code was reported as
6% authored, on the strength of having Dependabot switched on. This check
exists to notice a repository presented as larger than the work in it, and a
bot maintaining dependencies is not that.
"""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.vendored import is_vendored


def check_inflation(ctx: RepoContext, settings: Settings) -> list[Finding]:
    total = 0
    authored = 0
    vendored_example: str | None = None

    for commit in ctx.human_commits:
        for change in commit.files:
            total += change.insertions
            if is_vendored(change.path):
                vendored_example = vendored_example or change.path
            else:
                authored += change.insertions

    if total < settings.inflation_min_total_loc or total == 0:
        return []

    share = authored / total
    if share >= settings.inflation_authored_share:
        return []

    return [
        Finding(
            check_id="provenance.template_inflation",
            severity=Severity.LOW,
            title="Repository size is mostly vendored code",
            rationale=(
                f"Of {total} lines added across the history, roughly {authored} "
                f"({share:.0%}) are authored code. The remainder is boilerplate or "
                "vendored dependencies, so headline size overstates the work."
            ),
            confidence=0.9,
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=vendored_example,
                    detail=f"authored {authored} of {total} lines",
                ),
            ),
        )
    ]

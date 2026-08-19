"""Forks presented as original work."""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.vendored import is_vendored


def check_fork_origin(ctx: RepoContext, settings: Settings) -> list[Finding]:
    if not ctx.commits:
        return []

    # Only a repository GitHub reports as a fork, or one that names a parent,
    # can be "a fork presented as original work". Commits this tool cannot
    # attribute are a different and much weaker fact: there is no upstream author
    # to point at, and `low_contribution` already reports it. Firing here on an
    # unforked repository accused every candidate whose git identity differs from
    # their GitHub login — a renamed account, most often — of passing off someone
    # else's work.
    is_fork = bool(ctx.metadata.get("fork")) or bool(ctx.metadata.get("parent"))
    if not is_fork:
        return []

    earliest = ctx.commits[0]

    own = ctx.authored_commits
    own_insertions = sum(
        f.insertions for c in own for f in c.files if not is_vendored(f.path)
    )
    total_insertions = sum(
        f.insertions for c in ctx.commits for f in c.files if not is_vendored(f.path)
    )
    if total_insertions < settings.fork_min_total_loc:
        return []

    own_share = own_insertions / total_insertions
    if own_share > 0.25:
        return []

    parent = ctx.metadata.get("parent") or {}
    parent_name = parent.get("full_name", "an upstream repository")
    origin = f"The repository is a fork of {parent_name}."

    return [
        Finding(
            check_id="provenance.fork_presented_as_original",
            severity=Severity.HIGH,
            title="Fork presented as original work",
            rationale=(
                f"{origin} The candidate contributed {own_insertions} of "
                f"{total_insertions} authored lines ({own_share:.0%}), and the earliest "
                "commits belong to the upstream author."
            ),
            confidence=0.85,
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=earliest.sha,
                    detail=f"earliest commit authored by {earliest.author_name}",
                ),
            ),
        )
    ]

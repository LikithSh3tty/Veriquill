"""Forks presented as original work."""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.vendored import is_vendored


def check_fork_origin(ctx: RepoContext, settings: Settings) -> list[Finding]:
    if not ctx.commits:
        return []

    is_fork = bool(ctx.metadata.get("fork"))
    earliest = ctx.commits[0]
    earliest_is_candidate = (
        earliest.author_email.lower() in ctx.identities
        or earliest.author_name.lower() in ctx.identities
    )
    if not is_fork and earliest_is_candidate:
        return []

    own = ctx.authored_commits
    own_insertions = sum(
        f.insertions for c in own for f in c.files if not is_vendored(f.path)
    )
    total_insertions = sum(
        f.insertions for c in ctx.commits for f in c.files if not is_vendored(f.path)
    )
    if total_insertions == 0:
        return []

    own_share = own_insertions / total_insertions
    if own_share > 0.25:
        return []

    parent = ctx.metadata.get("parent") or {}
    parent_name = parent.get("full_name", "an upstream repository")
    origin = (
        f"The repository is a fork of {parent_name}."
        if is_fork
        else "The earliest commits were authored by someone else."
    )

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
            confidence=0.85 if is_fork else 0.6,
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=earliest.sha,
                    detail=f"earliest commit authored by {earliest.author_name}",
                ),
            ),
        )
    ]

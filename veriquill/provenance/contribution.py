"""Contribution verification: did the candidate write these commits."""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity


def check_contribution(ctx: RepoContext, settings: Settings) -> list[Finding]:
    if not ctx.commits:
        return []

    own = ctx.authored_commits
    own_shas = {c.sha for c in own}
    share = len(own) / len(ctx.commits)
    if share >= settings.contribution_low_share:
        return []

    other_authors = sorted(
        {c.author_name for c in ctx.commits if c.sha not in own_shas}
    )[:3]

    return [
        Finding(
            check_id="provenance.low_contribution",
            severity=Severity.HIGH,
            title="Few or no commits authored by the candidate",
            rationale=(
                f"The candidate authored {len(own)} of {len(ctx.commits)} commits "
                f"({share:.0%}). Commit identity can differ from account identity when "
                "git is configured with a different email, so this may be a "
                "configuration artifact rather than an authorship question."
            ),
            confidence=0.7,
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=ctx.commits[0].sha,
                    detail=f"principal authors: {', '.join(other_authors) or 'unknown'}",
                ),
            ),
        )
    ]

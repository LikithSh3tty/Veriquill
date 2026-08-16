"""Bulk dumps: a whole codebase arriving with no development history."""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.github.history import Commit
from veriquill.vendored import is_vendored


def _authored_insertions(commit: Commit) -> int:
    return sum(f.insertions for f in commit.files if not is_vendored(f.path))


def check_bulk_dump(ctx: RepoContext, settings: Settings) -> list[Finding]:
    if not ctx.commits:
        return []

    per_commit = [_authored_insertions(commit) for commit in ctx.commits]
    total = sum(per_commit)
    if total < settings.bulk_dump_min_loc:
        return []

    first = per_commit[0]
    share = first / total
    if share < settings.bulk_dump_loc_share:
        return []

    return [
        Finding(
            check_id="provenance.bulk_dump",
            severity=Severity.HIGH,
            title="Codebase landed with no development history",
            rationale=(
                f"{first} of {total} authored lines ({share:.0%}) arrived in one commit, "
                "so the repository holds no record of how the code was built. Work "
                "developed privately and imported once looks identical."
            ),
            confidence=min(0.5 + share / 2, 0.9),
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=ctx.commits[0].sha,
                    detail=f"{first} lines in the first commit",
                ),
            ),
        )
    ]

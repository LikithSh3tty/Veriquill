"""Commit cadence.

Organic work is spread out. Thirty commits inside sixty seconds is a replay of
an already-finished codebase. This is a question for the recruiter, not proof:
a local repository imported in one scripted push produces the same shape.

Author dates, not committer dates. Rebase, cherry-pick, squash and
filter-branch all rewrite the committer date to the moment they ran while
leaving the author date alone, so twenty commits written over twenty days and
rebased once before merging carried twenty identical committer timestamps.
That read as a scripted push of finished work, at high severity, against a
candidate whose only unusual act was tidying their branch.

A genuine replay bunches both dates, so it is still caught. What stops being
caught is a normal git workflow.
"""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.github.history import Commit


def check_cadence(ctx: RepoContext, settings: Settings) -> list[Finding]:
    # Sorted by the date being measured, so the inner loop may stop at the
    # first commit outside the window. Bots are excluded: a batch of
    # dependency bumps is not the candidate's development rhythm.
    commits = sorted(ctx.human_commits, key=lambda commit: commit.authored_at)
    if len(commits) < settings.burst_min_commits:
        return []

    window = settings.burst_window_seconds
    largest_burst: list[Commit] = []

    for start in range(len(commits)):
        burst = [commits[start]]
        for later in commits[start + 1 :]:
            delta = (later.authored_at - commits[start].authored_at).total_seconds()
            if abs(delta) > window:
                break
            burst.append(later)
        if len(burst) > len(largest_burst):
            largest_burst = burst

    if len(largest_burst) < settings.burst_min_commits:
        return []

    share = len(largest_burst) / len(commits)
    severity = Severity.HIGH if share >= 0.5 else Severity.MEDIUM
    return [
        Finding(
            check_id="provenance.cadence_burst",
            severity=severity,
            title="Commit history landed in a burst",
            rationale=(
                f"{len(largest_burst)} of {len(commits)} commits were written within "
                f"{window} seconds of each other, which is consistent with a scripted "
                "push of finished work rather than iterative development. A one-shot "
                "import of a local repository produces the same pattern. This reads "
                "author dates, so a rebase does not produce it."
            ),
            confidence=min(0.5 + share / 2, 0.95),
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=commit.sha,
                    detail=commit.authored_at.isoformat(),
                )
                for commit in largest_burst[:5]
            ),
        )
    ]

"""Commit cadence.

Organic work is spread out. Thirty commits inside sixty seconds is a replay of
an already-finished codebase. This is a question for the recruiter, not proof:
a local repository imported in one scripted push produces the same shape.
"""

from __future__ import annotations

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.github.history import Commit


def check_cadence(ctx: RepoContext, settings: Settings) -> list[Finding]:
    commits = ctx.commits
    if len(commits) < settings.burst_min_commits:
        return []

    window = settings.burst_window_seconds
    largest_burst: list[Commit] = []

    for start in range(len(commits)):
        burst = [commits[start]]
        for later in commits[start + 1 :]:
            delta = (later.committed_at - commits[start].committed_at).total_seconds()
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
                f"{len(largest_burst)} of {len(commits)} commits were recorded within "
                f"{window} seconds of each other, which is consistent with a scripted "
                "push of finished work rather than iterative development. A one-shot "
                "import of a local repository produces the same pattern."
            ),
            confidence=min(0.5 + share / 2, 0.95),
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    commit_sha=commit.sha,
                    detail=commit.committed_at.isoformat(),
                )
                for commit in largest_burst[:5]
            ),
        )
    ]

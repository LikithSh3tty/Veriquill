"""Finding the evidence that bears on a claim.

Matching is deliberately conservative. A false match produces a false
contradiction, which is the failure mode section 16 names as the most harmful
thing this tool can do, so a claim with no confident match is reported as
unverifiable rather than forced onto the nearest repository.
"""

from __future__ import annotations

import re

from veriquill.claims.models import Claim, ClaimKind
from veriquill.reconcile.evidence import RepoEvidence

# Kinds a GitHub account simply cannot speak to.
UNMATCHABLE_KINDS = frozenset({ClaimKind.EDUCATION, ClaimKind.ENDORSEMENT})

_STOPWORDS = frozenset(
    """
    a an the of for with and or to in on at by from as is was were be been being
    built build building led lead leading worked work working using used use
    team project projects service services system systems tool tools code
    developed develop developing created create creating my our their new
    """.split()
)

_WORD = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str) -> set[str]:
    words = _WORD.findall(text.lower().replace("-", " ").replace("_", " "))
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def match_claim(claim: Claim, repos: list[RepoEvidence]) -> list[RepoEvidence]:
    """Repositories that bear on this claim, most relevant first."""
    if claim.kind in UNMATCHABLE_KINDS:
        return []

    subject = (claim.subject or "").strip().lower()
    scored: list[tuple[float, RepoEvidence]] = []

    for repo in repos:
        haystack = repo.search_text
        score = 0.0

        if subject:
            normalised = subject.replace("-", " ").replace("_", " ")
            if normalised == repo.name.replace("-", " ").replace("_", " "):
                score += 10.0
            elif normalised in haystack:
                score += 4.0
            if subject in {lang.lower() for lang in repo.languages}:
                score += 6.0

        # Fall back to distinctive-word overlap for prose claims that name no
        # subject (a role or achievement sentence).
        if score == 0.0 and not subject:
            overlap = _tokens(claim.text) & _tokens(haystack)
            if len(overlap) >= 2:
                score += float(len(overlap))

        if score > 0:
            scored.append((score, repo))

    scored.sort(key=lambda pair: (-pair[0], pair[1].full_name))
    return [repo for _, repo in scored]

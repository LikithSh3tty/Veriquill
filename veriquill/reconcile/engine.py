"""Claim against evidence: the component the specification calls the payoff.

Every material claim is either corroborated by work the candidate demonstrably
authored, contradicted by work that turns out not to be theirs, or left
unverifiable. Evidence with no matching claim runs the comparison the other
way and surfaces as an undisclosed strength.

Nothing here is a verdict on a person. Each result is a question with its
sources attached.
"""

from __future__ import annotations

from veriquill.claims.models import Claim, ClaimKind
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.reconcile.matcher import UNMATCHABLE_KINDS, match_claim
from veriquill.reconcile.models import Reconciliation, Verdict

# Below this share of commits, a matched repository does not support a claim
# of having built the thing.
_WEAK_AUTHORSHIP = 0.1

# Only these kinds assert that the candidate *made* something, so only these
# can be contradicted by authorship evidence. "I know Ruby" is not a claim to
# have authored any particular Ruby repository: finding one they did not write
# fails to support the skill, but it does not refute it. Treating it as a
# contradiction would manufacture exactly the false accusation section 16
# names as this tool's most harmful failure.
AUTHORSHIP_CLAIMS = frozenset(
    {ClaimKind.PROJECT, ClaimKind.ROLE, ClaimKind.ACHIEVEMENT}
)


def _judge(claim: Claim, matches: list[RepoEvidence]) -> Reconciliation:
    if not matches:
        if claim.kind in UNMATCHABLE_KINDS:
            rationale = (
                "No public artifact can confirm or deny this kind of claim. "
                "Noted without weight."
            )
        else:
            rationale = (
                "No public repository matches this claim. It may describe "
                "private or employer-owned work, so it is noted without being "
                "credited or penalised."
            )
        return Reconciliation(
            verdict=Verdict.UNVERIFIABLE,
            rationale=rationale,
            confidence=0.5,
            claim=claim,
        )

    supporting = [
        repo
        for repo in matches
        if not repo.disputes_authorship and repo.authorship_share > _WEAK_AUTHORSHIP
    ]

    if supporting:
        best = supporting[0]
        return Reconciliation(
            verdict=Verdict.CORROBORATED,
            rationale=(
                f"{best.full_name} supports this claim: the candidate authored "
                f"{best.authored_commits} of {best.total_commits} commits "
                f"({best.authorship_share:.0%})."
            ),
            confidence=min(0.6 + best.authorship_share / 2, 0.95),
            claim=claim,
            evidence=tuple(supporting),
        )

    if claim.kind not in AUTHORSHIP_CLAIMS:
        return Reconciliation(
            verdict=Verdict.UNVERIFIABLE,
            rationale=(
                "The repositories that mention this were not authored by the "
                "candidate, so they do not support the claim. A skill can be "
                "held without having authored any particular repository, so "
                "this is not evidence against it either."
            ),
            confidence=0.5,
            claim=claim,
            evidence=tuple(matches),
        )

    worst = matches[0]
    return Reconciliation(
        verdict=Verdict.CONTRADICTED,
        rationale=(
            f"The only matching repository, {worst.full_name}, was not authored "
            f"by the candidate: {worst.authored_commits} of "
            f"{worst.total_commits} commits ({worst.authorship_share:.0%}). "
            "Commit identity can differ from account identity, so this is a "
            "question to put to the candidate rather than a conclusion."
        ),
        confidence=0.7,
        claim=claim,
        evidence=tuple(matches),
    )


def reconcile(
    claims: list[Claim], repos: list[RepoEvidence]
) -> list[Reconciliation]:
    results: list[Reconciliation] = []
    claimed: set[str] = set()

    for claim in claims:
        matches = match_claim(claim, repos)
        for repo in matches:
            claimed.add(repo.full_name)
        results.append(_judge(claim, matches))

    for repo in repos:
        if repo.full_name in claimed:
            continue
        if not repo.is_substantial or repo.disputes_authorship:
            continue
        results.append(
            Reconciliation(
                verdict=Verdict.UNDISCLOSED,
                rationale=(
                    f"{repo.full_name} is substantial work the candidate authored "
                    f"({repo.authored_commits} commits, ~{repo.authored_loc} "
                    "authored lines) but never mentioned."
                ),
                confidence=0.8,
                evidence=(repo,),
            )
        )

    return sorted(results, key=lambda r: (r.verdict.rank, -r.confidence))

from veriquill.claims.models import Claim, ClaimKind, ClaimSource
from veriquill.reconcile.engine import reconcile
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.reconcile.models import Verdict

OWNED = RepoEvidence(
    full_name="cand/veriquill",
    description="Provenance engine for hiring",
    languages={"Python": 20},
    authored_commits=40,
    total_commits=40,
    authored_loc=3000,
)
NOT_REALLY_THEIRS = RepoEvidence(
    full_name="cand/payments",
    description="Payments service",
    languages={"Python": 8},
    authored_commits=0,
    total_commits=60,
    authored_loc=0,
    check_ids=("provenance.low_contribution",),
)
UNMENTIONED = RepoEvidence(
    full_name="cand/scheduler",
    description="Distributed job scheduler",
    languages={"Go": 15},
    authored_commits=55,
    total_commits=55,
    authored_loc=4200,
)


def _claim(kind: ClaimKind, text: str, subject: str | None = None) -> Claim:
    return Claim(
        kind=kind,
        text=text,
        source=ClaimSource(document="resume.txt", locator="line 1", excerpt=text),
        subject=subject,
    )


def test_a_claim_backed_by_authored_work_is_corroborated():
    claim = _claim(ClaimKind.PROJECT, "veriquill", subject="veriquill")
    results = reconcile([claim], [OWNED])

    assert results[0].verdict is Verdict.CORROBORATED
    assert results[0].evidence[0].full_name == "cand/veriquill"


def test_a_claim_matched_only_to_work_the_candidate_did_not_author_is_contradicted():
    claim = _claim(ClaimKind.PROJECT, "payments", subject="payments")
    results = reconcile([claim], [NOT_REALLY_THEIRS])

    assert results[0].verdict is Verdict.CONTRADICTED
    assert "authored" in results[0].rationale.lower()


def _for_claim(results, claim):
    """The result judging this claim.

    An unmatched claim also leaves the repository unclaimed, so the run
    legitimately returns an undisclosed-strength entry alongside it.
    """
    return next(r for r in results if r.claim is claim)


def test_a_claim_with_no_matching_repository_is_unverifiable():
    claim = _claim(ClaimKind.SKILL, "Kubernetes", subject="kubernetes")
    results = reconcile([claim], [OWNED])

    assert _for_claim(results, claim).verdict is Verdict.UNVERIFIABLE


def test_unverifiable_is_neither_credited_nor_penalised():
    """Section 7: claimed private work with no public evidence is noted only."""
    claim = _claim(ClaimKind.ROLE, "Led an internal trading platform")
    result = _for_claim(reconcile([claim], [OWNED]), claim)

    assert result.verdict is Verdict.UNVERIFIABLE
    assert result.counts_against is False
    assert result.counts_for is False


def test_a_contradiction_counts_against_and_a_corroboration_counts_for():
    corroborated = reconcile(
        [_claim(ClaimKind.PROJECT, "veriquill", subject="veriquill")], [OWNED]
    )[0]
    contradicted = reconcile(
        [_claim(ClaimKind.PROJECT, "payments", subject="payments")], [NOT_REALLY_THEIRS]
    )[0]

    assert corroborated.counts_for is True
    assert contradicted.counts_against is True


def test_substantial_unclaimed_work_is_surfaced_as_undisclosed():
    claim = _claim(ClaimKind.PROJECT, "veriquill", subject="veriquill")
    results = reconcile([claim], [OWNED, UNMENTIONED])

    undisclosed = [r for r in results if r.verdict is Verdict.UNDISCLOSED]
    assert len(undisclosed) == 1
    assert undisclosed[0].evidence[0].full_name == "cand/scheduler"


def test_undisclosed_work_counts_in_the_candidates_favour():
    results = reconcile([], [UNMENTIONED])
    assert results[0].verdict is Verdict.UNDISCLOSED
    assert results[0].counts_for is True


def test_work_the_candidate_did_not_author_is_not_called_undisclosed():
    """Surfacing someone else's repository as a hidden strength would be wrong."""
    results = reconcile([], [NOT_REALLY_THEIRS])
    assert results == []


def test_trivial_repositories_are_not_surfaced_as_undisclosed():
    tiny = RepoEvidence(
        full_name="cand/dotfiles",
        authored_commits=3,
        total_commits=3,
        authored_loc=40,
    )
    assert reconcile([], [tiny]) == []


def test_every_result_keeps_the_claim_provenance():
    claim = _claim(ClaimKind.PROJECT, "veriquill", subject="veriquill")
    result = reconcile([claim], [OWNED])[0]

    assert result.claim is not None
    assert result.claim.source.locator == "line 1"


def test_results_are_ordered_most_decisive_first():
    claims = [
        _claim(ClaimKind.SKILL, "Kubernetes", subject="kubernetes"),
        _claim(ClaimKind.PROJECT, "payments", subject="payments"),
        _claim(ClaimKind.PROJECT, "veriquill", subject="veriquill"),
    ]
    verdicts = [r.verdict for r in reconcile(claims, [OWNED, NOT_REALLY_THEIRS])]

    assert verdicts[0] is Verdict.CONTRADICTED
    assert verdicts.index(Verdict.CORROBORATED) < verdicts.index(Verdict.UNVERIFIABLE)

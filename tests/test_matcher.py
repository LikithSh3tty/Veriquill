from veriquill.claims.models import Claim, ClaimKind, ClaimSource
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.reconcile.matcher import match_claim

VERIQUILL = RepoEvidence(
    full_name="cand/veriquill",
    description="Provenance engine and static code evaluation for hiring",
    topics=("hiring",),
    languages={"Python": 20},
    authored_commits=40,
    total_commits=40,
    authored_loc=3000,
)
SIDE_PROJECT = RepoEvidence(
    full_name="cand/pixel-art-editor",
    description="A tiny canvas editor",
    languages={"JavaScript": 4},
    authored_commits=12,
    total_commits=12,
    authored_loc=800,
)
REPOS = [VERIQUILL, SIDE_PROJECT]


def _claim(kind: ClaimKind, text: str, subject: str | None = None) -> Claim:
    return Claim(
        kind=kind,
        text=text,
        source=ClaimSource(document="resume.txt", locator="line 1", excerpt=text),
        subject=subject,
    )


def test_a_project_claim_matches_the_repo_of_the_same_name():
    claim = _claim(ClaimKind.PROJECT, "veriquill - hiring tool", subject="veriquill")
    assert match_claim(claim, REPOS) == [VERIQUILL]


def test_a_language_skill_matches_repos_written_in_it():
    claim = _claim(ClaimKind.SKILL, "Python", subject="python")
    assert match_claim(claim, REPOS) == [VERIQUILL]


def test_a_skill_named_in_a_description_matches():
    claim = _claim(ClaimKind.SKILL, "provenance", subject="provenance")
    assert VERIQUILL in match_claim(claim, REPOS)


def test_a_near_miss_phrase_does_not_match():
    """"static analysis" is not "static code evaluation".

    Matching is deliberately literal. Guessing that two similar phrases mean
    the same thing is how a claim gets attached to the wrong repository and
    then reported as contradicted, which section 16 names as the most harmful
    failure mode this tool has.
    """
    claim = _claim(ClaimKind.SKILL, "static analysis", subject="static analysis")
    assert match_claim(claim, REPOS) == []


def test_a_skill_with_no_supporting_repo_matches_nothing():
    claim = _claim(ClaimKind.SKILL, "Kubernetes", subject="kubernetes")
    assert match_claim(claim, REPOS) == []


def test_a_role_claim_matches_on_distinctive_words():
    claim = _claim(ClaimKind.ROLE, "Built the provenance engine for hiring")
    assert VERIQUILL in match_claim(claim, REPOS)


def test_common_words_alone_do_not_create_a_match():
    """'Built a tool for the team' shares only stopwords with every repo."""
    claim = _claim(ClaimKind.ROLE, "Worked on a and the of for with team")
    assert match_claim(claim, REPOS) == []


def test_matching_is_case_and_separator_insensitive():
    claim = _claim(ClaimKind.PROJECT, "Pixel Art Editor", subject="pixel art editor")
    assert match_claim(claim, REPOS) == [SIDE_PROJECT]


def test_an_education_claim_is_never_matched_to_a_repository():
    """A degree is not the sort of thing a GitHub account can corroborate."""
    claim = _claim(ClaimKind.EDUCATION, "M.Sc. Artificial Intelligence, Python heavy")
    assert match_claim(claim, REPOS) == []

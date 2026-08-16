from veriquill.reconcile.evidence import RepoEvidence


def _evidence(**kwargs) -> RepoEvidence:
    base = dict(
        full_name="cand/veriquill",
        description="Provenance engine and code evaluation",
        topics=("hiring", "static-analysis"),
        languages={"Python": 12},
        authored_commits=40,
        total_commits=40,
        authored_loc=3000,
        check_ids=(),
    )
    base.update(kwargs)
    return RepoEvidence(**base)


def test_repo_name_is_the_short_name():
    assert _evidence().name == "veriquill"


def test_search_text_covers_name_description_topics_and_languages():
    text = _evidence().search_text
    assert "veriquill" in text
    assert "provenance" in text
    assert "static-analysis" in text
    assert "python" in text


def test_authorship_share_is_a_fraction():
    assert _evidence(authored_commits=10, total_commits=40).authorship_share == 0.25


def test_authorship_share_of_an_empty_repo_is_zero():
    assert _evidence(authored_commits=0, total_commits=0).authorship_share == 0.0


def test_substantial_requires_authorship_and_size():
    assert _evidence().is_substantial is True
    assert _evidence(authored_commits=0).is_substantial is False
    assert _evidence(authored_loc=5).is_substantial is False


def test_a_repo_flagged_for_authorship_is_not_credited_to_the_candidate():
    flagged = _evidence(check_ids=("provenance.low_contribution",))
    assert flagged.disputes_authorship is True
    assert _evidence(check_ids=("codeeval.no_tests",)).disputes_authorship is False

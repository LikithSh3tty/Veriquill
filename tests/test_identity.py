"""Matching commits to the person who wrote them.

A GitHub account can be renamed, and its old login keeps appearing in every
commit already pushed under it. The numeric account id does not change, and the
noreply address carries it, so matching on the id survives a rename where
matching on the login string does not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from veriquill.context import RepoContext
from veriquill.github.history import Commit


def _ctx(commits: list[Commit], identities: set[str], user_id: int | None = None) -> RepoContext:
    return RepoContext(
        full_name="cand/repo",
        path=Path("."),
        candidate_handle="likithsh3tty",
        identities=frozenset(i.lower() for i in identities),
        commits=commits,
        metadata={},
        user_id=user_id,
    )


_WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _commit(name: str, email: str, sha: str = "a1") -> Commit:
    return Commit(
        sha=sha,
        author_name=name,
        author_email=email,
        authored_at=_WHEN,
        committer_name=name,
        committer_email=email,
        committed_at=_WHEN,
        parents=(),
        files=(),
    )


def test_a_commit_under_the_current_login_is_matched():
    ctx = _ctx([_commit("LikithSh3tty", "likith@example.com")], {"likithsh3tty"})

    assert len(ctx.authored_commits) == 1


def test_a_commit_under_a_previous_login_is_matched_by_account_id():
    """Renaming the account must not turn its own history into someone else's."""
    ctx = _ctx(
        [_commit("lucifer360", "12345+lucifer360@users.noreply.github.com")],
        {"likithsh3tty"},
        user_id=12345,
    )

    assert len(ctx.authored_commits) == 1


def test_a_different_account_id_in_a_noreply_address_is_not_matched():
    ctx = _ctx(
        [_commit("someone", "999+someone@users.noreply.github.com")],
        {"likithsh3tty"},
        user_id=12345,
    )

    assert ctx.authored_commits == []


def test_a_noreply_address_without_an_id_still_matches_a_known_login():
    ctx = _ctx(
        [_commit("old", "lucifer360@users.noreply.github.com")],
        {"likithsh3tty", "lucifer360"},
        user_id=12345,
    )

    assert len(ctx.authored_commits) == 1


def test_a_declared_alias_is_matched():
    """A candidate who says 'I also committed as X' is taken at their word."""
    ctx = _ctx([_commit("lucifer360", "dev@local")], {"likithsh3tty", "lucifer360"})

    assert len(ctx.authored_commits) == 1


def test_an_unrelated_author_is_still_not_the_candidate():
    ctx = _ctx([_commit("Someone Else", "else@example.com")], {"likithsh3tty"}, user_id=12345)

    assert ctx.authored_commits == []


def test_matching_is_case_insensitive():
    ctx = _ctx([_commit("LIKITHSH3TTY", "LIKITH@EXAMPLE.COM")], {"likithsh3tty"})

    assert len(ctx.authored_commits) == 1


def test_an_account_without_an_id_falls_back_to_name_and_email_matching():
    ctx = _ctx([_commit("lucifer360", "12345+lucifer360@users.noreply.github.com")], {"lucifer360"})

    assert len(ctx.authored_commits) == 1

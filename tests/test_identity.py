"""Matching commits to the person who wrote them.

A GitHub account can be renamed, and its old login keeps appearing in every
commit already pushed under it. The numeric account id does not change, and the
noreply address carries it, so matching on the id survives a rename where
matching on the login string does not.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from veriquill.context import RepoContext
from veriquill.github.history import Commit
from veriquill.github.ingest import fetch_identity


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


# --- aliases, and the fact that nothing could reach them --------------------


class _RealProfile:
    """A real account: renamed, with its email private.

    Taken from running Veriquill against a live portfolio. The account was once
    `lucifer360` and is now `LikithSh3tty`, and one of its repositories was
    committed from a machine whose git config said `Dev <dev@local>`.
    """

    async def get_json(self, path: str) -> dict:
        return {"login": "LikithSh3tty", "id": 75750335, "name": "Likith Shetty", "email": None}


def _authored(name: str, email: str) -> Commit:
    moment = _WHEN
    return Commit(
        sha="a" * 40,
        author_name=name,
        author_email=email,
        authored_at=moment,
        committer_name=name,
        committer_email=email,
        committed_at=moment,
        parents=(),
        files=(),
    )


def _context(identity: dict) -> RepoContext:
    return RepoContext(
        full_name="LikithSh3tty/Agenvo",
        path=Path("."),
        candidate_handle="LikithSh3tty",
        identities=identity["identities"],
        user_id=identity["user_id"],
    )


def test_a_renamed_account_still_owns_its_old_commits():
    """No alias needed: the noreply address carries the numeric id."""
    identity = asyncio.run(fetch_identity(_RealProfile(), "LikithSh3tty"))
    old_login = _authored("lucifer360", "75750335+lucifer360@users.noreply.github.com")

    assert _context(identity).is_candidate(old_login) is True


def test_a_different_git_config_reads_as_somebody_else_without_an_alias():
    """The real false positive: 4 of 106 commits, on a repository they wrote."""
    identity = asyncio.run(fetch_identity(_RealProfile(), "LikithSh3tty"))

    assert _context(identity).is_candidate(_authored("Dev", "dev@local")) is False


def test_an_alias_puts_those_commits_back():
    identity = asyncio.run(
        fetch_identity(_RealProfile(), "LikithSh3tty", frozenset({"Dev", "dev@local"}))
    )

    assert _context(identity).is_candidate(_authored("Dev", "dev@local")) is True


def test_the_cli_can_supply_aliases():
    """They were unreachable: the parameter existed and no caller passed it."""
    from veriquill.cli import _aliases

    assert _aliases(["Dev", " dev@local ", ""]) == frozenset({"Dev", "dev@local"})


def test_the_api_can_supply_aliases():
    from veriquill.api.main import _split_aliases

    assert _split_aliases("Dev, dev@local ,") == frozenset({"Dev", "dev@local"})


# --- what GitHub attributes, versus what a profile lets us guess -------------


class AttributionClient:
    """Answers /repos/.../commits the way GitHub does, for one signing address."""

    def __init__(self, entries):
        self.entries = entries
        self.paths: list[str] = []

    async def get_json(self, path, params=None):
        self.paths.append(path)
        return self.entries


async def test_the_address_github_links_becomes_an_identity():
    """The profile cannot supply it, so it has to be asked for.

    TJ Holowaychuk's account is `tj`, his display name is `TJ`, and his commits
    say `TJ Holowaychuk <tj@vision-media.ca>`. Nothing assembled from the
    profile matches that, so five repositories he wrote read as zero commits
    authored and each earned a high severity flag.
    """
    from veriquill.github.ingest import attributed_identities

    client = AttributionClient(
        [
            {
                "author": {"login": "tj"},
                "commit": {"author": {"name": "TJ Holowaychuk", "email": "tj@vision-media.ca"}},
            }
        ]
    )

    found = await attributed_identities(client, ["tj/commander.js"], "tj")

    assert "tj@vision-media.ca" in found
    assert "tj holowaychuk" in found


async def test_a_commit_github_did_not_link_is_not_borrowed():
    """An unlinked commit is exactly the guesswork this replaces."""
    from veriquill.github.ingest import attributed_identities

    client = AttributionClient(
        [
            {
                "author": None,
                "commit": {"author": {"name": "Someone Else", "email": "else@example.com"}},
            },
            {
                "author": {"login": "notthem"},
                "commit": {"author": {"name": "Third Party", "email": "third@example.com"}},
            },
        ]
    )

    assert await attributed_identities(client, ["tj/commander.js"], "tj") == frozenset()


async def test_a_failed_lookup_leaves_the_guesses_alone():
    """An enrichment that raises would fail an analysis over an extra address."""
    from veriquill.github.ingest import attributed_identities

    class Broken:
        async def get_json(self, path, params=None):
            raise RuntimeError("rate limited")

    assert await attributed_identities(Broken(), ["a/b"], "tj") == frozenset()


def test_an_attributed_address_counts_the_commits_it_signs():
    """The point of the lookup: those commits stop reading as somebody else's."""
    from datetime import UTC, datetime

    from veriquill.context import RepoContext
    from veriquill.github.history import Commit

    _NOW = datetime.now(UTC)

    def commit(email):
        return Commit(
            sha="a" * 40,
            author_name="TJ Holowaychuk",
            author_email=email,
            authored_at=_NOW,
            committer_name="TJ Holowaychuk",
            committer_email=email,
            committed_at=_NOW,
            parents=(),
            files=(),
        )

    guessed = frozenset({"tj", "tj@users.noreply.github.com"})
    ctx = RepoContext(
        full_name="tj/commander.js",
        path=None,
        candidate_handle="tj",
        identities=guessed,
        commits=[commit("tj@vision-media.ca")],
        metadata={},
    )
    assert ctx.authored_commits == []

    enriched = RepoContext(
        full_name="tj/commander.js",
        path=None,
        candidate_handle="tj",
        identities=guessed | {"tj@vision-media.ca"},
        commits=[commit("tj@vision-media.ca")],
        metadata={},
    )
    assert len(enriched.authored_commits) == 1

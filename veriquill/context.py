"""The unit of work every engine receives."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veriquill.github.history import Commit

# GitHub's private-address forms: <login>@users.noreply.github.com and the newer
# <account id>+<login>@users.noreply.github.com. The login in either is whatever
# the account was called when the commit was made.
_NOREPLY = re.compile(
    r"^(?:(?P<id>\d+)\+)?(?P<login>[^@+]+)@users\.noreply\.github\.com$"
)


@dataclass(frozen=True, slots=True)
class RepoContext:
    full_name: str
    path: Path
    candidate_handle: str
    identities: frozenset[str]
    commits: list[Commit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    user_id: int | None = None

    def is_candidate(self, commit: Commit) -> bool:
        """Whether this commit was written by the candidate.

        A GitHub account can be renamed, and every commit already pushed keeps
        the old login. The numeric account id does not change and the noreply
        address carries it, so an id match is what survives a rename. Without
        it, a renamed account's own history reads as somebody else's work —
        which is the most damaging thing this tool could get wrong.
        """
        email = commit.author_email.lower()
        if email in self.identities or commit.author_name.lower() in self.identities:
            return True

        noreply = _NOREPLY.match(email)
        if noreply is None:
            return False
        if noreply["id"] is not None and self.user_id is not None:
            return noreply["id"] == str(self.user_id)
        # An older address carries no id, so the login it names is all there is.
        return noreply["login"] in self.identities

    @property
    def authored_commits(self) -> list[Commit]:
        """Commits whose author matches one of the candidate's known identities."""
        return [commit for commit in self.commits if self.is_candidate(commit)]

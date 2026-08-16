"""The unit of work every engine receives."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veriquill.github.history import Commit


@dataclass(frozen=True, slots=True)
class RepoContext:
    full_name: str
    path: Path
    candidate_handle: str
    identities: frozenset[str]
    commits: list[Commit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def authored_commits(self) -> list[Commit]:
        """Commits whose author matches one of the candidate's known identities."""
        return [
            commit
            for commit in self.commits
            if commit.author_email.lower() in self.identities
            or commit.author_name.lower() in self.identities
        ]

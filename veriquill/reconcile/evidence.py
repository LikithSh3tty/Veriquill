"""The evidence side of reconciliation.

A `RepoEvidence` is the flattened, comparable view of everything the GitHub
engines learned about one repository. Reconciliation works against this rather
than the raw context so the matching rules stay readable and testable without
a clone on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Provenance findings that say the candidate did not really author this work.
# A claim matched only to such a repository is contradicted, not corroborated.
AUTHORSHIP_DISPUTES = frozenset(
    {
        "provenance.low_contribution",
        "provenance.fork_presented_as_original",
    }
)

_MIN_SUBSTANTIAL_LOC = 200


@dataclass(frozen=True, slots=True)
class RepoEvidence:
    full_name: str
    description: str = ""
    topics: tuple[str, ...] = ()
    languages: dict[str, int] = field(default_factory=dict)
    authored_commits: int = 0
    total_commits: int = 0
    authored_loc: int = 0
    check_ids: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.full_name.split("/")[-1]

    @property
    def search_text(self) -> str:
        parts = [
            self.name.replace("-", " ").replace("_", " "),
            self.description or "",
            " ".join(self.topics),
            " ".join(self.languages),
        ]
        return " ".join(parts).lower()

    @property
    def authorship_share(self) -> float:
        if self.total_commits <= 0:
            return 0.0
        return self.authored_commits / self.total_commits

    @property
    def is_substantial(self) -> bool:
        """Enough authored work to be worth surfacing on its own."""
        return self.authored_commits > 0 and self.authored_loc >= _MIN_SUBSTANTIAL_LOC

    @property
    def disputes_authorship(self) -> bool:
        return any(check in AUTHORSHIP_DISPUTES for check in self.check_ids)

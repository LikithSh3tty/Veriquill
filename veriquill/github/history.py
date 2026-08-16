"""Commit graph extraction.

Everything here comes from the clone. No REST call is made, so history of any
size costs nothing against the hourly quota.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_RECORD = "\x1e"
_FIELD = "\x1f"
_PRETTY = (
    f"{_RECORD}%H{_FIELD}%an{_FIELD}%ae{_FIELD}%aI"
    f"{_FIELD}%cn{_FIELD}%ce{_FIELD}%cI{_FIELD}%P"
)


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    insertions: int
    deletions: int


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    authored_at: datetime
    committer_name: str
    committer_email: str
    committed_at: datetime
    parents: tuple[str, ...]
    files: tuple[FileChange, ...]

    @property
    def insertions(self) -> int:
        return sum(f.insertions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)


def _parse_numstat(line: str) -> FileChange | None:
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    added, removed, path = parts
    # Binary files report "-" instead of a count.
    return FileChange(
        path=path,
        insertions=0 if added == "-" else int(added),
        deletions=0 if removed == "-" else int(removed),
    )


def read_history(repo_path: Path) -> list[Commit]:
    # `--numstat` diffs every commit, which reads blobs. Against a partial
    # clone git would silently fetch each missing blob from the remote, one
    # round trip at a time, turning a 20-second read into hours. Refuse to go
    # to the network: fail loudly instead of stalling.
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            "--all",
            f"--pretty=format:{_PRETTY}",
            "--numstat",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    if result.returncode != 0:
        # An empty repository has no HEAD; that is not an error condition.
        if "does not have any commits yet" in result.stderr:
            return []
        raise RuntimeError(f"git log failed in {repo_path}: {result.stderr.strip()}")

    commits: list[Commit] = []
    for record in result.stdout.split(_RECORD):
        if not record.strip():
            continue
        lines = record.strip("\n").split("\n")
        fields = lines[0].split(_FIELD)
        if len(fields) < 8:
            continue
        sha, an, ae, aiso, cn, ce, ciso, parents = fields[:8]
        files = tuple(
            change
            for change in (_parse_numstat(line) for line in lines[1:] if line.strip())
            if change is not None
        )
        commits.append(
            Commit(
                sha=sha,
                author_name=an,
                author_email=ae,
                authored_at=datetime.fromisoformat(aiso),
                committer_name=cn,
                committer_email=ce,
                committed_at=datetime.fromisoformat(ciso),
                parents=tuple(p for p in parents.split(" ") if p),
                files=files,
            )
        )

    commits.reverse()  # git log is newest first; analysis wants oldest first
    return commits

"""Builds real git repositories with scripted histories.

Ground truth is known because these fixtures authored it, and no network
access is needed to test the provenance engine.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class CommitSpec:
    message: str
    files: dict[str, str]
    when: datetime
    author_name: str = "Candidate"
    author_email: str = "candidate@example.com"
    #: When git last wrote the commit, if that differs from when the work was
    #: authored. Rebase, cherry-pick and squash all set this to the moment
    #: they ran, which is the shape a rebased branch has and a scripted dump
    #: does not. Defaults to the author date.
    committed: datetime | None = None


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env=env)


def build_repo(base: Path, name: str, commits: list[CommitSpec]) -> Path:
    repo = base / name
    repo.mkdir(parents=True)
    _run(["git", "init", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.name", "Fixture"], cwd=repo)
    _run(["git", "config", "user.email", "fixture@example.com"], cwd=repo)

    for spec in commits:
        for rel, content in spec.files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        _run(["git", "add", "-A"], cwd=repo)
        stamp = spec.when.isoformat()
        written = (spec.committed or spec.when).isoformat()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": spec.author_name,
            "GIT_AUTHOR_EMAIL": spec.author_email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_NAME": spec.author_name,
            "GIT_COMMITTER_EMAIL": spec.author_email,
            "GIT_COMMITTER_DATE": written,
        }
        _run(["git", "commit", "-m", spec.message], cwd=repo, env=env)

    return repo


def organic_history(start: datetime | None = None) -> list[CommitSpec]:
    """Twelve commits spread over twelve days: what real work looks like."""
    start = start or datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    specs: list[CommitSpec] = []
    for day in range(12):
        specs.append(
            CommitSpec(
                message=f"step {day}",
                files={f"src/module_{day}.py": f"def f{day}():\n    return {day}\n"},
                when=start + timedelta(days=day, hours=day % 5),
            )
        )
    return specs


def burst_history(start: datetime | None = None, count: int = 30) -> list[CommitSpec]:
    """Thirty commits inside one minute: a scripted replay, not development."""
    start = start or datetime(2025, 3, 1, 2, 0, tzinfo=timezone.utc)
    return [
        CommitSpec(
            message=f"chunk {i}",
            files={f"src/part_{i}.py": "x = 1\n" * 20},
            when=start + timedelta(seconds=i),
        )
        for i in range(count)
    ]


def bulk_dump_history(start: datetime | None = None) -> list[CommitSpec]:
    """One enormous first commit, then trivial follow-ups."""
    start = start or datetime(2025, 5, 1, 9, 0, tzinfo=timezone.utc)
    big = {f"src/file_{i}.py": "line = 1\n" * 200 for i in range(12)}
    return [
        CommitSpec(message="initial commit", files=big, when=start),
        CommitSpec(
            message="update readme",
            files={"README.md": "# project\n"},
            when=start + timedelta(days=1),
        ),
    ]

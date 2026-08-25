"""Deciding whether a repository has moved, without cloning it.

The rule these tests hold: a commit sha covers its whole ancestry, so two
histories with the same head sha are the same history. That makes a fingerprint
over every ref sound against exactly what this tool exists to notice. A
force-push, a rebase, a squash and an amended root commit all change a sha; a
deleted branch changes the set.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from veriquill.eval.fixtures import CommitSpec, build_repo
from veriquill.github.refs import RefsUnavailable, account_fingerprint, fingerprint, read_refs

_ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _repo(tmp_path: Path, name: str, count: int = 3) -> Path:
    specs = [
        CommitSpec(
            message=f"step {i}",
            files={f"src/m{i}.py": f"x = {i}\n"},
            when=_ORIGIN + timedelta(days=i),
        )
        for i in range(count)
    ]
    return build_repo(tmp_path, name, specs)


def _refs(path: Path) -> dict[str, str]:
    return asyncio.run(read_refs(str(path), timeout=30))


def test_a_local_repository_advertises_its_refs(tmp_path):
    refs = _refs(_repo(tmp_path, "plain"))

    assert refs
    assert any(name.endswith("/main") for name in refs)


def test_an_unreadable_remote_is_refused_rather_than_guessed(tmp_path):
    with pytest.raises(RefsUnavailable):
        asyncio.run(read_refs(str(tmp_path / "does-not-exist"), timeout=30))


def test_the_same_history_fingerprints_the_same(tmp_path):
    repo = _repo(tmp_path, "stable")

    assert fingerprint({"c/r": _refs(repo)}) == fingerprint({"c/r": _refs(repo)})


def test_a_new_commit_changes_the_fingerprint(tmp_path):
    repo = _repo(tmp_path, "growing")
    before = fingerprint({"c/r": _refs(repo)})

    (repo / "src" / "extra.py").write_text("y = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "more"], cwd=repo, check=True, capture_output=True)

    assert fingerprint({"c/r": _refs(repo)}) != before


def test_a_rewritten_history_changes_the_fingerprint(tmp_path):
    """The case the rule exists for: same content, rewritten commits."""
    repo = _repo(tmp_path, "rewritten")
    before = fingerprint({"c/r": _refs(repo)})

    # Amending the tip rewrites its sha, and any descendant would follow.
    subprocess.run(
        ["git", "commit", "--amend", "-m", "reworded"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    assert fingerprint({"c/r": _refs(repo)}) != before


def test_a_deleted_branch_changes_the_fingerprint(tmp_path):
    """No sha was rewritten, so hashing shas alone would miss this."""
    repo = _repo(tmp_path, "branched")
    subprocess.run(["git", "branch", "spike"], cwd=repo, check=True, capture_output=True)
    before = fingerprint({"c/r": _refs(repo)})

    subprocess.run(["git", "branch", "-D", "spike"], cwd=repo, check=True, capture_output=True)

    assert fingerprint({"c/r": _refs(repo)}) != before


def test_the_tool_version_is_part_of_the_fingerprint(monkeypatch, tmp_path):
    """A new check has to re-read a repository that has not changed."""
    from veriquill.github import refs as refs_module

    refs = _refs(_repo(tmp_path, "versioned"))
    before = fingerprint({"c/r": refs})

    monkeypatch.setattr(refs_module, "__version__", "999.0.0")

    assert fingerprint({"c/r": refs}) != before


def test_a_repository_naming_change_is_a_change(tmp_path):
    refs = _refs(_repo(tmp_path, "named"))

    assert fingerprint({"c/one": refs}) != fingerprint({"c/two": refs})


def test_an_account_fingerprint_covers_every_repository(tmp_path):
    one = _repo(tmp_path, "one")
    two = _repo(tmp_path, "two")

    both = asyncio.run(
        account_fingerprint({"c/one": str(one), "c/two": str(two)}, timeout=30)
    )
    just_one = asyncio.run(account_fingerprint({"c/one": str(one)}, timeout=30))

    assert both is not None
    assert both != just_one


def test_an_unanswerable_question_is_never_read_as_no_change(tmp_path):
    """A repository gone private must re-analyse, not serve a stale dossier."""
    one = _repo(tmp_path, "reachable")

    result = asyncio.run(
        account_fingerprint(
            {"c/one": str(one), "c/gone": str(tmp_path / "missing")}, timeout=30
        )
    )

    assert result is None

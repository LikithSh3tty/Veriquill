import asyncio
import sys
import time

import pytest

from tests.fixtures.repobuilder import build_repo, organic_history
from veriquill.github import clone as clone_module
from veriquill.github.clone import CloneError, clone_repo, ephemeral_clone
from veriquill.github.history import read_history


async def test_ephemeral_clone_copies_history_and_cleans_up(tmp_path):
    source = build_repo(tmp_path / "src", "origin", organic_history())
    workdir = tmp_path / "work"

    async with ephemeral_clone(source.as_uri(), workdir, timeout=60) as clone_path:
        assert clone_path.exists()
        assert len(read_history(clone_path)) == 12
        captured = clone_path

    assert not captured.exists()


async def test_clone_failure_raises_clone_error(tmp_path):
    with pytest.raises(CloneError):
        async with ephemeral_clone(
            (tmp_path / "does-not-exist").as_uri(), tmp_path / "work", timeout=30
        ):
            pass


async def test_a_hanging_clone_is_killed_at_the_timeout(tmp_path, monkeypatch):
    """A stalled transfer must not be able to stall the whole run.

    Wrapping `communicate()` in `wait_for` passes on POSIX and deadlocks on
    Windows, where cancelling a pending overlapped pipe read never completes.
    This drives a stand-in for git that hangs, so the timeout path itself is
    exercised rather than assumed.
    """
    hanging_git = tmp_path / "hanging_git.py"
    hanging_git.write_text("import time\ntime.sleep(600)\n", encoding="utf-8")

    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(_program, *args, **kwargs):
        if _program == "taskkill":
            return await real_exec(_program, *args, **kwargs)
        return await real_exec(sys.executable, str(hanging_git), **kwargs)

    monkeypatch.setattr(clone_module.asyncio, "create_subprocess_exec", fake_exec)

    started = time.monotonic()
    with pytest.raises(CloneError, match="timed out"):
        await clone_repo("https://example.invalid/repo.git", tmp_path / "dest", timeout=2)
    elapsed = time.monotonic() - started

    assert elapsed < 30, f"timeout did not fire promptly (took {elapsed:.1f}s)"

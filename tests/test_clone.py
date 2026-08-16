import pytest

from tests.fixtures.repobuilder import build_repo, organic_history
from veriquill.github.clone import CloneError, ephemeral_clone
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

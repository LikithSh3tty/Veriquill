import pytest

from veriquill.vendored import authored_files, is_vendored


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/left-pad/index.js",
        "vendor/github.com/pkg/errors.go",
        "dist/bundle.min.js",
        "static/js/jquery.min.js",
        "package-lock.json",
        "poetry.lock",
        ".venv/lib/site-packages/foo.py",
        "migrations/0001_initial.py",
    ],
)
def test_vendored_paths_are_recognised(path):
    assert is_vendored(path) is True


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "veriquill/config.py", "tests/test_app.py", "README.md"],
)
def test_authored_paths_are_not_vendored(path):
    assert is_vendored(path) is False


def test_authored_files_skips_vendored_trees_and_git(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "node_modules" / "dep").mkdir(parents=True)
    (tmp_path / "node_modules" / "dep" / "index.js").write_text("y = 2\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")

    found = {p.as_posix() for p in authored_files(tmp_path)}
    assert found == {"src/app.py"}

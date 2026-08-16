from datetime import datetime, timezone

from tests.fixtures.repobuilder import CommitSpec, build_repo, organic_history
from veriquill.github.history import read_history


def test_history_is_oldest_first_with_authorship(tmp_path):
    repo = build_repo(tmp_path, "organic", organic_history())
    commits = read_history(repo)

    assert len(commits) == 12
    assert commits[0].authored_at < commits[-1].authored_at
    assert commits[0].author_email == "candidate@example.com"
    assert commits[0].parents == ()
    assert commits[1].parents == (commits[0].sha,)


def test_history_records_per_file_line_counts(tmp_path):
    repo = build_repo(
        tmp_path,
        "counted",
        [
            CommitSpec(
                message="add",
                files={"a.py": "one\ntwo\nthree\n"},
                when=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )
        ],
    )
    commits = read_history(repo)

    assert commits[0].files[0].path == "a.py"
    assert commits[0].files[0].insertions == 3
    assert commits[0].insertions == 3


def test_empty_repository_yields_no_commits(tmp_path):
    repo = build_repo(tmp_path, "empty", [])
    assert read_history(repo) == []

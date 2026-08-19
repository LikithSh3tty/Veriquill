"""Choosing which repositories to read when an account has too many.

Cloning twenty repositories to answer a question about five is slow and wasteful,
but choosing badly is worse than choosing slowly: a candidate whose relevant work
is skipped is judged on the wrong evidence. So selection runs on metadata GitHub
already gave us, records why each repository was chosen or skipped, and never
pretends the unread ones were read.
"""

from __future__ import annotations

from veriquill.relevance import DEFAULT_LIMIT, select_repositories


def repo(name: str, language: str | None = None, **kwargs) -> dict:
    return {
        "name": name,
        "full_name": f"cand/{name}",
        "language": language,
        "description": kwargs.get("description", ""),
        "topics": kwargs.get("topics", []),
        "size": kwargs.get("size", 100),
        "fork": kwargs.get("fork", False),
        "pushed_at": kwargs.get("pushed_at", "2026-01-01T00:00:00Z"),
    }


def test_a_small_account_is_read_in_full():
    repos = [repo(f"r{i}") for i in range(4)]

    selected, skipped = select_repositories(repos, "", limit=5, threshold=20)

    assert len(selected) == 4
    assert skipped == []


def test_an_account_under_the_threshold_is_never_trimmed():
    repos = [repo(f"r{i}") for i in range(19)]

    selected, skipped = select_repositories(repos, "", limit=5, threshold=20)

    assert len(selected) == 19
    assert skipped == []


def test_a_large_account_is_trimmed_to_the_limit():
    repos = [repo(f"r{i}") for i in range(25)]

    selected, skipped = select_repositories(repos, "", limit=5, threshold=20)

    assert len(selected) == 5
    assert len(skipped) == 20


def test_the_job_description_language_wins_the_places():
    repos = [repo(f"js{i}", "JavaScript") for i in range(20)] + [
        repo("api", "Python"),
        repo("worker", "Python"),
    ]

    selected, _ = select_repositories(
        repos, "Backend engineer writing Python services.", limit=3, threshold=10
    )

    names = [r["repository"]["name"] for r in selected]
    assert "api" in names and "worker" in names


def test_a_topic_that_matches_the_posting_counts():
    repos = [repo(f"r{i}") for i in range(20)] + [
        repo("payments", topics=["payments", "stripe"])
    ]

    selected, _ = select_repositories(
        repos, "You will work on payments and billing.", limit=2, threshold=10
    )

    assert "payments" in [r["repository"]["name"] for r in selected]


def test_a_description_that_matches_the_posting_counts():
    repos = [repo(f"r{i}") for i in range(20)] + [
        repo("infra", description="Kubernetes operators for internal infrastructure")
    ]

    selected, _ = select_repositories(
        repos, "Experience with Kubernetes is required.", limit=2, threshold=10
    )

    assert "infra" in [r["repository"]["name"] for r in selected]


def test_a_fork_loses_to_original_work_of_the_same_relevance():
    repos = [repo(f"r{i}") for i in range(20)] + [
        repo("mine", "Python", size=500),
        repo("theirs", "Python", size=500, fork=True),
    ]

    selected, _ = select_repositories(repos, "Python", limit=1, threshold=10)

    assert selected[0]["repository"]["name"] == "mine"


def test_every_selected_repository_says_why_it_was_chosen():
    repos = [repo(f"r{i}", "Python") for i in range(25)]

    selected, _ = select_repositories(repos, "Python services", limit=5, threshold=20)

    for row in selected:
        assert row["reasons"], f"{row['repository']['name']} was chosen with no reason given"


def test_every_skipped_repository_is_named():
    repos = [repo(f"r{i}") for i in range(25)]

    _, skipped = select_repositories(repos, "", limit=5, threshold=20)

    for row in skipped:
        assert row["repository"]["name"]
        assert row["reason"]


def test_selection_is_deterministic():
    repos = [repo(f"r{i}", "Python", size=i * 10) for i in range(25)]

    first, _ = select_repositories(repos, "Python", limit=5, threshold=20)
    second, _ = select_repositories(repos, "Python", limit=5, threshold=20)

    assert [r["repository"]["name"] for r in first] == [
        r["repository"]["name"] for r in second
    ]


def test_without_a_posting_the_biggest_and_newest_win():
    repos = [
        repo("tiny", size=1, pushed_at="2020-01-01T00:00:00Z"),
        repo("large-recent", size=9000, pushed_at="2026-08-01T00:00:00Z"),
    ] + [repo(f"r{i}") for i in range(20)]

    selected, _ = select_repositories(repos, "", limit=1, threshold=10)

    assert selected[0]["repository"]["name"] == "large-recent"


def test_the_default_limit_is_a_handful_not_everything():
    assert 1 <= DEFAULT_LIMIT <= 10

"""Choosing which repositories to read when an account has too many.

Cloning twenty repositories to answer a question about five is slow and wasteful,
but choosing badly is worse than choosing slowly: a candidate whose relevant work
is skipped is judged on the wrong evidence. So selection runs on metadata GitHub
already gave us, records why each repository was chosen or skipped, and never
pretends the unread ones were read.
"""

from __future__ import annotations

from veriquill.relevance import DEFAULT_LIMIT, _languages_named, select_repositories


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


def test_the_english_word_go_does_not_name_the_go_language():
    """'go-getter' and 'go far' are prose, not a language requirement."""
    assert set(_languages_named("We want a go-getter who will go far.")) == set()
    assert set(_languages_named("Go the extra mile for our customers.")) == set()


def test_go_named_as_a_language_still_counts():
    for posting in (
        "Backend engineer writing Go services.",
        "Experience in Go is required.",
        "We are hiring a Golang developer.",
        "Our stack is Go, Postgres and Kafka.",
        "You will write code in Go and Python.",
    ):
        assert "Go" in _languages_named(posting), posting


def test_swift_as_an_adjective_does_not_name_the_swift_language():
    assert set(_languages_named("We pride ourselves on swift delivery.")) == set()
    assert "Swift" in _languages_named("You will build our iOS app in Swift.")


def test_an_ambiguous_language_only_wins_places_when_the_posting_names_it():
    """A tiny stale Go repo must not outrank a large recent one on prose alone."""
    repos = [repo("flagship", "Ruby", size=9000, pushed_at="2026-08-01T00:00:00Z")]
    repos += [repo(f"filler{i}") for i in range(20)]
    repos += [repo("tool", "Go", size=1, pushed_at="2019-01-01T00:00:00Z")]

    prose, _ = select_repositories(repos, "We want a go-getter.", limit=1, threshold=10)
    assert prose[0]["repository"]["name"] == "flagship"

    named, _ = select_repositories(repos, "Backend engineer writing Go.", limit=1, threshold=10)
    assert named[0]["repository"]["name"] == "tool"


def test_a_framework_implies_the_language_it_is_written_in():
    """A posting says "Django and React". It never says "Python" or "TypeScript"."""
    assert "Python" in _languages_named("You will work on our Django monolith.")
    assert "TypeScript" in _languages_named("Frontend built with React and Next.js.")
    assert "JavaScript" in _languages_named("Frontend built with React and Next.js.")
    assert "Ruby" in _languages_named("Our app is Rails.")
    assert "Java" in _languages_named("Spring Boot microservices.")
    assert "C#" in _languages_named("An ASP.NET Core service.")
    assert "PHP" in _languages_named("A Laravel codebase.")
    assert "Swift" in _languages_named("You will ship our SwiftUI app.")


def test_a_framework_posting_selects_the_right_repositories():
    repos = [repo(f"js{i}", "JavaScript", size=900) for i in range(20)] + [
        repo("api", "Python", size=1, pushed_at="2019-01-01T00:00:00Z")
    ]

    selected, _ = select_repositories(
        repos, "Backend engineer for our Django services.", limit=1, threshold=10
    )

    assert selected[0]["repository"]["name"] == "api"


def test_an_implied_language_says_which_word_implied_it():
    repos = [repo(f"r{i}") for i in range(20)] + [repo("api", "Python")]

    selected, _ = select_repositories(repos, "Django and Celery.", limit=2, threshold=10)

    reasons = " ".join(
        r for row in selected for r in row["reasons"] if row["repository"]["name"] == "api"
    )
    assert "django" in reasons.lower()


def test_a_language_named_outright_still_reads_as_named_not_implied():
    repos = [repo(f"r{i}") for i in range(20)] + [repo("api", "Python")]

    selected, _ = select_repositories(repos, "Python services.", limit=2, threshold=10)

    reasons = " ".join(
        r for row in selected for r in row["reasons"] if row["repository"]["name"] == "api"
    )
    assert "names" in reasons.lower()

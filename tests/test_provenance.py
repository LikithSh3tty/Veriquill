from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.fixtures.repobuilder import (
    CommitSpec,
    build_repo,
    bulk_dump_history,
    burst_history,
    organic_history,
)
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Severity
from veriquill.github.history import Commit, FileChange, read_history
from veriquill.provenance import (
    check_bulk_dump,
    check_cadence,
    check_contribution,
    check_fork_origin,
    check_inflation,
)
from veriquill.provenance.duplication import check_duplication, fingerprint_repo
from veriquill.provenance.engine import run_provenance

IDENTITIES = frozenset({"candidate@example.com", "candidate"})


def _ctx(tmp_path: Path, name: str, commits, metadata=None) -> RepoContext:
    repo = build_repo(tmp_path, name, commits)
    return RepoContext(
        full_name=f"cand/{name}",
        path=repo,
        candidate_handle="cand",
        identities=IDENTITIES,
        commits=read_history(repo),
        metadata=metadata or {},
    )


def _settings(tmp_path) -> Settings:
    return Settings(github_token="t", data_dir=tmp_path / "data")


# --- cadence -------------------------------------------------------------


def test_burst_history_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "burst", burst_history())
    findings = check_cadence(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.cadence_burst"
    assert findings[0].severity in (Severity.HIGH, Severity.MEDIUM)
    assert findings[0].evidence[0].commit_sha


def test_organic_history_produces_no_cadence_flag(tmp_path):
    ctx = _ctx(tmp_path, "organic", organic_history())
    assert check_cadence(ctx, _settings(tmp_path)) == []


# --- bulk dump -----------------------------------------------------------


def test_bulk_dump_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "dump", bulk_dump_history())
    findings = check_bulk_dump(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.bulk_dump"
    assert "one commit" in findings[0].rationale.lower()


def test_organic_history_produces_no_bulk_dump_flag(tmp_path):
    ctx = _ctx(tmp_path, "organic2", organic_history())
    assert check_bulk_dump(ctx, _settings(tmp_path)) == []


# --- fork / origin -------------------------------------------------------


def test_fork_with_only_downstream_readme_commit_is_flagged(tmp_path):
    start = datetime(2025, 2, 1, tzinfo=timezone.utc)
    commits = [
        CommitSpec(
            message="upstream work",
            # Comfortably above settings.fork_min_total_loc: the check
            # deliberately ignores repositories too small to judge.
            files={"src/core.py": "x = 1\n" * 400},
            when=start,
            author_name="Upstream Author",
            author_email="upstream@example.com",
        ),
        CommitSpec(
            message="readme",
            files={"README.md": "# mine\n"},
            when=start + timedelta(days=30),
        ),
    ]
    ctx = _ctx(
        tmp_path,
        "forked",
        commits,
        metadata={"fork": True, "parent": {"full_name": "upstream/core"}},
    )
    findings = check_fork_origin(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.fork_presented_as_original"
    assert findings[0].evidence[0].detail


def test_non_fork_produces_no_fork_flag(tmp_path):
    ctx = _ctx(tmp_path, "own", organic_history(), metadata={"fork": False})
    assert check_fork_origin(ctx, _settings(tmp_path)) == []


def test_a_trivially_small_repo_is_not_called_a_fork(tmp_path):
    """Precision guard: a 3-line repo authored by someone else is a real fact,
    but "fork presented as original work" at HIGH severity overstates it."""
    commits = [
        CommitSpec(
            message="one small commit",
            files={"README.md": "# hi\n"},
            when=datetime(2025, 7, 1, tzinfo=timezone.utc),
            author_name="Someone Else",
            author_email="someone@example.com",
        )
    ]
    ctx = _ctx(tmp_path, "tiny", commits, metadata={"fork": False})
    assert check_fork_origin(ctx, _settings(tmp_path)) == []


# --- inflation -----------------------------------------------------------


def test_vendored_bulk_is_flagged_as_inflation(tmp_path):
    start = datetime(2025, 4, 1, tzinfo=timezone.utc)
    commits = [
        CommitSpec(
            message="add deps and a little code",
            files={
                **{f"node_modules/dep{i}/index.js": "z = 1\n" * 400 for i in range(8)},
                "src/app.py": "def main():\n    return 1\n",
            },
            when=start,
        )
    ]
    ctx = _ctx(tmp_path, "inflated", commits)
    findings = check_inflation(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.template_inflation"
    assert findings[0].severity is Severity.LOW


def test_clean_repo_produces_no_inflation_flag(tmp_path):
    ctx = _ctx(tmp_path, "clean", organic_history())
    assert check_inflation(ctx, _settings(tmp_path)) == []


# --- contribution --------------------------------------------------------


def test_repo_authored_by_someone_else_is_flagged(tmp_path):
    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    commits = [
        CommitSpec(
            message=f"work {i}",
            files={f"src/f{i}.py": "a = 1\n"},
            when=start + timedelta(days=i),
            author_name="Other Person",
            author_email="other@example.com",
        )
        for i in range(10)
    ]
    ctx = _ctx(tmp_path, "notmine", commits)
    findings = check_contribution(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.low_contribution"
    assert findings[0].severity is Severity.HIGH


def test_own_repo_produces_no_contribution_flag(tmp_path):
    ctx = _ctx(tmp_path, "mine", organic_history())
    assert check_contribution(ctx, _settings(tmp_path)) == []


# --- duplication ---------------------------------------------------------


def test_identical_codebase_on_another_profile_is_info(tmp_path):
    ctx = _ctx(tmp_path, "shared", organic_history())
    hashes = fingerprint_repo(ctx)
    known = {"otherperson:otherperson/shared": hashes}

    findings = check_duplication(ctx, _settings(tmp_path), known)

    assert findings
    assert findings[0].check_id == "provenance.cross_profile_duplicate"
    assert findings[0].severity is Severity.INFO


def test_own_prior_run_is_not_a_duplicate(tmp_path):
    ctx = _ctx(tmp_path, "solo", organic_history())
    known = {"cand:cand/solo": fingerprint_repo(ctx)}
    assert check_duplication(ctx, _settings(tmp_path), known) == []


# --- engine --------------------------------------------------------------


def test_engine_sorts_most_severe_first(tmp_path):
    ctx = _ctx(tmp_path, "messy", bulk_dump_history() + burst_history())
    findings = run_provenance(ctx, _settings(tmp_path), known_fingerprints={})

    ranks = [f.severity.rank for f in findings]
    assert ranks == sorted(ranks)


def test_healthy_repo_produces_no_flags_at_all(tmp_path):
    ctx = _ctx(tmp_path, "healthy", organic_history(), metadata={"fork": False})
    assert run_provenance(ctx, _settings(tmp_path), known_fingerprints={}) == []


def test_an_unforked_repository_is_never_called_a_fork(tmp_path):
    """The most damaging overstatement this tool could make.

    A repository GitHub reports as original, whose commits carry an identity we
    cannot match, supports exactly one claim: we could not attribute the work.
    There is no upstream author to point at, and `low_contribution` already
    reports the underlying fact.
    """
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commits = [
        CommitSpec(
            message=f"work {i}",
            files={f"src/mod_{i}.py": "x = 1\n" * 200},
            when=start + timedelta(days=i),
            author_name="lucifer360",
            author_email="lucifer360@example.com",
        )
        for i in range(6)
    ]
    ctx = _ctx(tmp_path, "renamed", commits, metadata={"fork": False})

    findings = check_fork_origin(ctx, _settings(tmp_path))

    assert findings == [], "a repository that is not a fork must not be called one"


def test_a_real_fork_is_still_flagged(tmp_path):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    commits = [
        CommitSpec(
            message=f"upstream {i}",
            files={f"src/core_{i}.py": "y = 1\n" * 200},
            when=start + timedelta(days=i),
            author_name="Upstream Author",
            author_email="upstream@example.com",
        )
        for i in range(6)
    ]
    ctx = _ctx(
        tmp_path,
        "forked",
        commits,
        metadata={"fork": True, "parent": {"full_name": "upstream/core"}},
    )

    findings = check_fork_origin(ctx, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "provenance.fork_presented_as_original"
    assert "upstream/core" in findings[0].rationale


#: One base moment for every synthetic history below.
_ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --- machines are not co-authors, and not co-suspects ----------------------


def _commit(index: int, name: str, email: str, files=()) -> Commit:
    moment = _ORIGIN + timedelta(hours=index)
    return Commit(
        sha=f"{index:040x}",
        author_name=name,
        author_email=email,
        authored_at=moment,
        committer_name=name,
        committer_email=email,
        committed_at=moment,
        parents=(),
        files=files,
    )


def _bot_ctx(commits) -> RepoContext:
    return RepoContext(
        full_name="cand/app",
        path=Path("."),
        candidate_handle="cand",
        identities=frozenset({"cand", "cand@example.com"}),
        commits=commits,
        user_id=42,
    )


@pytest.mark.parametrize(
    "name,email",
    [
        ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
        ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"),
        ("renovate", "renovate@whitesourcesoftware.com"),
        ("pre-commit-ci[bot]", "66853113+pre-commit-ci[bot]@users.noreply.github.com"),
    ],
)
def test_known_automation_is_recognised(name, email):
    assert RepoContext.is_bot(_commit(1, name, email)) is True


def test_a_person_is_not_mistaken_for_automation():
    assert RepoContext.is_bot(_commit(1, "Alice Robotham", "alice@example.com")) is False


def test_dependabot_does_not_cost_the_candidate_their_authorship(tmp_path):
    """They wrote every human commit. Sixty bumps reported them at 17%."""
    human = [_commit(i, "cand", "cand@example.com") for i in range(12)]
    bots = [
        _commit(100 + i, "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
        for i in range(60)
    ]

    findings = check_contribution(_bot_ctx(human + bots), _settings(tmp_path))

    assert findings == []


def test_a_genuinely_absent_author_is_still_reported(tmp_path):
    """The exclusion must not have swallowed the check."""
    mine = [_commit(i, "cand", "cand@example.com") for i in range(12)]
    theirs = [_commit(100 + i, "Someone Else", "else@example.com") for i in range(60)]

    findings = check_contribution(_bot_ctx(mine + theirs), _settings(tmp_path))

    assert [f.check_id for f in findings] == ["provenance.low_contribution"]


def test_a_repository_of_only_bot_commits_is_not_judged(tmp_path):
    bots = [
        _commit(i, "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
        for i in range(20)
    ]

    assert check_contribution(_bot_ctx(bots), _settings(tmp_path)) == []


def test_lockfile_churn_is_not_template_inflation(tmp_path):
    """A bot rewrites the whole lockfile per bump, so sixty bumps count it sixty
    times. Three thousand lines of real code read as 6% authored."""
    human = [
        _commit(i, "cand", "cand@example.com", (FileChange("src/app.py", 100, 0),))
        for i in range(30)
    ]
    bumps = [
        _commit(
            100 + i,
            "dependabot[bot]",
            "49699333+dependabot[bot]@users.noreply.github.com",
            (FileChange("package-lock.json", 800, 800),),
        )
        for i in range(60)
    ]

    assert check_inflation(_bot_ctx(human + bumps), _settings(tmp_path)) == []


def test_a_candidate_committing_a_vendored_tree_is_still_inflation(tmp_path):
    human = [
        _commit(i, "cand", "cand@example.com", (FileChange("src/app.py", 100, 0),))
        for i in range(30)
    ]
    dumped = [
        _commit(
            200 + i,
            "cand",
            "cand@example.com",
            (FileChange("node_modules/pkg/index.js", 900, 0),),
        )
        for i in range(60)
    ]

    findings = check_inflation(_bot_ctx(human + dumped), _settings(tmp_path))

    assert [f.check_id for f in findings] == ["provenance.template_inflation"]


# --- cadence reads when work was written, not when it was last rewritten ----


def _dated(index: int, authored, committed) -> Commit:
    return Commit(
        sha=f"{index:040x}",
        author_name="cand",
        author_email="cand@example.com",
        authored_at=authored,
        committer_name="cand",
        committer_email="cand@example.com",
        committed_at=committed,
        parents=(),
        files=(FileChange("src/app.py", 10, 0),),
    )


#: When the rebase ran, long after the work it rewrote.
_REBASED = _ORIGIN + timedelta(days=59, hours=12)


def test_rebasing_a_branch_is_not_a_scripted_push(tmp_path):
    """Rebase rewrites every committer date to the moment it ran.

    Twenty commits written over twenty days then rebased once carried twenty
    identical committer timestamps, and were reported at high severity as a
    replay of finished work.
    """
    spread = [_ORIGIN + timedelta(days=i) for i in range(20)]
    rebased = [_dated(i, when, _REBASED + timedelta(seconds=i)) for i, when in enumerate(spread)]

    assert check_cadence(_bot_ctx(rebased), _settings(tmp_path)) == []


def test_the_same_work_unrebased_is_also_quiet(tmp_path):
    spread = [_ORIGIN + timedelta(days=i) for i in range(20)]
    natural = [_dated(i, when, when) for i, when in enumerate(spread)]

    assert check_cadence(_bot_ctx(natural), _settings(tmp_path)) == []


def test_a_genuine_replay_is_still_caught(tmp_path):
    """Both dates bunched: the work itself was never spread out."""
    dumped = [
        _dated(i, _REBASED + timedelta(seconds=i), _REBASED + timedelta(seconds=i))
        for i in range(20)
    ]

    findings = check_cadence(_bot_ctx(dumped), _settings(tmp_path))

    assert [f.check_id for f in findings] == ["provenance.cadence_burst"]


def test_a_batch_of_bot_commits_is_not_the_candidates_rhythm(tmp_path):
    spread = [_ORIGIN + timedelta(days=i) for i in range(12)]
    human = [_dated(i, when, when) for i, when in enumerate(spread)]
    burst_moment = _ORIGIN + timedelta(days=40)
    bots = [
        Commit(
            sha=f"{500 + i:040x}",
            author_name="dependabot[bot]",
            author_email="49699333+dependabot[bot]@users.noreply.github.com",
            authored_at=burst_moment + timedelta(seconds=i),
            committer_name="dependabot[bot]",
            committer_email="49699333+dependabot[bot]@users.noreply.github.com",
            committed_at=burst_moment + timedelta(seconds=i),
            parents=(),
            files=(FileChange("package-lock.json", 800, 800),),
        )
        for i in range(20)
    ]

    assert check_cadence(_bot_ctx(human + bots), _settings(tmp_path)) == []


def test_a_formatter_bot_does_not_push_a_fork_over_the_threshold(tmp_path):
    """Every other provenance ratio excludes bots; this one is the last.

    A formatter or docs generator committing to a fork writes lines that are
    neither the upstream author's nor the candidate's, and counting them only
    ever pushes the candidate's share down toward the threshold.
    """
    upstream = [
        Commit(
            sha=f"{i:040x}",
            author_name="Upstream",
            author_email="upstream@example.com",
            authored_at=_ORIGIN + timedelta(days=i),
            committer_name="Upstream",
            committer_email="upstream@example.com",
            committed_at=_ORIGIN + timedelta(days=i),
            parents=(),
            files=(FileChange("src/core.py", 100, 0),),
        )
        for i in range(10)
    ]
    mine = [
        _dated(100 + i, _ORIGIN + timedelta(days=20 + i), _ORIGIN + timedelta(days=20 + i))
        for i in range(60)
    ]
    formatter = [
        Commit(
            sha=f"{500 + i:040x}",
            author_name="pre-commit-ci[bot]",
            author_email="66853113+pre-commit-ci[bot]@users.noreply.github.com",
            authored_at=_ORIGIN + timedelta(days=90 + i),
            committer_name="pre-commit-ci[bot]",
            committer_email="66853113+pre-commit-ci[bot]@users.noreply.github.com",
            committed_at=_ORIGIN + timedelta(days=90 + i),
            parents=(),
            files=(FileChange("src/formatted.py", 400, 400),),
        )
        for i in range(20)
    ]

    ctx = RepoContext(
        full_name="cand/forked",
        path=Path("."),
        candidate_handle="cand",
        identities=frozenset({"cand", "cand@example.com"}),
        commits=upstream + mine + formatter,
        metadata={"fork": True, "parent": {"full_name": "upstream/original"}},
        user_id=42,
    )

    assert check_fork_origin(ctx, _settings(tmp_path)) == []


def test_a_fork_the_candidate_barely_touched_is_still_reported(tmp_path):
    upstream = [
        Commit(
            sha=f"{i:040x}",
            author_name="Upstream",
            author_email="upstream@example.com",
            authored_at=_ORIGIN + timedelta(days=i),
            committer_name="Upstream",
            committer_email="upstream@example.com",
            committed_at=_ORIGIN + timedelta(days=i),
            parents=(),
            files=(FileChange("src/core.py", 500, 0),),
        )
        for i in range(10)
    ]
    mine = [_dated(100, _ORIGIN + timedelta(days=30), _ORIGIN + timedelta(days=30))]

    ctx = RepoContext(
        full_name="cand/forked",
        path=Path("."),
        candidate_handle="cand",
        identities=frozenset({"cand", "cand@example.com"}),
        commits=upstream + mine,
        metadata={"fork": True, "parent": {"full_name": "upstream/original"}},
        user_id=42,
    )

    findings = check_fork_origin(ctx, _settings(tmp_path))

    assert [f.check_id for f in findings] == ["provenance.fork_presented_as_original"]

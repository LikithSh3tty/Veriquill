from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from veriquill.github.history import read_history
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

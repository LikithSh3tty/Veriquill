from tests.fixtures.repobuilder import build_repo, bulk_dump_history, organic_history
from veriquill.config import Settings
from veriquill.pipeline import analyse_candidate


class FakeClient:
    """Stands in for GitHubClient: returns local clone URLs instead of GitHub."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


async def test_run_summary_collects_findings_per_repository(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    good = build_repo(sources, "good", organic_history())
    bad = build_repo(sources, "bad", bulk_dump_history())

    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate@example.com", "candidate"})}

    async def fake_repos(client, handle):
        return [
            {"full_name": "cand/good", "clone_url": good.as_uri(), "fork": False},
            {"full_name": "cand/bad", "clone_url": bad.as_uri(), "fork": False},
        ]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    by_name = {r.full_name: r for r in summary.repositories}
    # The organic repository earns no authenticity flag. It does earn code-eval
    # findings (it has no tests), which is a separate judgment.
    assert [
        f.check_id
        for f in by_name["cand/good"].findings
        if f.check_id.startswith("provenance.")
    ] == []
    assert any(f.check_id == "provenance.bulk_dump" for f in by_name["cand/bad"].findings)
    assert summary.to_dict()["handle"] == "cand"


async def test_unclonable_repository_records_an_error_not_a_flag(tmp_path, monkeypatch):
    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate"})}

    async def fake_repos(client, handle):
        return [
            {
                "full_name": "cand/missing",
                "clone_url": (tmp_path / "nope").as_uri(),
                "fork": False,
            }
        ]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    result = summary.repositories[0]
    assert result.error is not None
    assert result.findings == []


async def test_every_finding_in_a_summary_cites_evidence(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    bad = build_repo(sources, "bad", bulk_dump_history())

    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate@example.com", "candidate"})}

    async def fake_repos(client, handle):
        return [{"full_name": "cand/bad", "clone_url": bad.as_uri(), "fork": False}]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    payload = summary.to_dict()
    findings = [f for repo in payload["repositories"] for f in repo["findings"]]
    assert findings
    assert all(f["evidence"] for f in findings)


async def test_evidence_is_built_for_each_analysed_repository(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    good = build_repo(sources, "good", organic_history())

    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate@example.com", "candidate"})}

    async def fake_repos(client, handle):
        return [
            {
                "full_name": "cand/good",
                "clone_url": good.as_uri(),
                "fork": False,
                "description": "an organic repository",
                "topics": ["demo"],
            }
        ]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    evidence = summary.repositories[0].evidence
    assert evidence is not None
    assert evidence.full_name == "cand/good"
    assert evidence.description == "an organic repository"
    assert evidence.topics == ("demo",)
    assert evidence.authored_commits == 12
    assert evidence.total_commits == 12
    assert evidence.languages.get("Python")


async def test_a_failed_repository_carries_no_evidence(tmp_path, monkeypatch):
    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate"})}

    async def fake_repos(client, handle):
        return [{"full_name": "cand/missing", "clone_url": (tmp_path / "nope").as_uri()}]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    assert summary.repositories[0].evidence is None


def test_authorship_share_is_measured_against_people(tmp_path):
    """Automation in the denominator can contradict a true resume claim.

    Reconciliation treats a repository as supporting a claim only above a
    minimum authorship share. With two hundred Dependabot bumps counted, a
    candidate's own project fell under it and their claim to have built the
    thing came back contradicted.
    """
    from datetime import datetime, timedelta, timezone

    from veriquill.context import RepoContext
    from veriquill.github.history import Commit, FileChange
    from veriquill.pipeline import build_evidence

    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def made_by(index: int, name: str, email: str) -> Commit:
        moment = origin + timedelta(hours=index)
        return Commit(
            sha=f"{index:040x}",
            author_name=name,
            author_email=email,
            authored_at=moment,
            committer_name=name,
            committer_email=email,
            committed_at=moment,
            parents=(),
            files=(FileChange("src/app.py", 40, 0),),
        )

    mine = [made_by(i, "cand", "cand@example.com") for i in range(12)]
    bots = [
        made_by(100 + i, "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
        for i in range(200)
    ]

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    ctx = RepoContext(
        full_name="cand/orchard",
        path=root,
        candidate_handle="cand",
        identities=frozenset({"cand", "cand@example.com"}),
        commits=mine + bots,
        user_id=42,
    )

    evidence = build_evidence(ctx, [])

    assert evidence.total_commits == 12
    assert evidence.authorship_share == 1.0


async def test_analysing_one_repository_does_not_stall_the_others(tmp_path, monkeypatch):
    """The slow part of an analysis must not freeze the loop the clones run on.

    Reading a clone is entirely synchronous: git log over the whole history,
    bandit and ruff as subprocesses, then a hash of every authored file. Run
    directly on the event loop that is also cloning three other repositories,
    it stops them dead, and their clone timeouts expire while nothing is
    downloading. A real portfolio reported three repositories as unclonable
    after three hundred seconds each; every one of them clones by hand in under
    five.

    So this measures the loop rather than the outcome: a heartbeat ticks every
    ten milliseconds throughout, and the assertion is that it kept ticking
    while the slow work was in progress.
    """
    import asyncio
    import time

    sources = tmp_path / "sources"
    repo = build_repo(sources, "slow", organic_history())

    async def fake_identity(client, handle, aliases=frozenset()):
        return {"identities": frozenset({"candidate"})}

    async def fake_repos(client, handle):
        return [{"full_name": "cand/slow", "clone_url": repo.as_uri(), "fork": False}]

    window: list[float] = []

    def slow_codeeval(ctx, settings):
        window.append(time.monotonic())
        time.sleep(0.5)
        window.append(time.monotonic())
        return []

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)
    monkeypatch.setattr("veriquill.pipeline.run_codeeval", slow_codeeval)

    beats: list[float] = []

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(0.01)
            beats.append(time.monotonic())

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    pulse = asyncio.create_task(heartbeat())
    try:
        await analyse_candidate("cand", settings, client=FakeClient())
    finally:
        pulse.cancel()

    assert len(window) == 2, "the slow analysis never ran"
    start, end = window
    during = [b for b in beats if start <= b <= end]
    # Half a second of ten millisecond ticks is fifty; a blocked loop manages
    # none. Ten is far enough from both to survive a loaded machine.
    assert len(during) >= 10, (
        f"the event loop was blocked during analysis: {len(during)} ticks "
        f"in {end - start:.2f}s"
    )

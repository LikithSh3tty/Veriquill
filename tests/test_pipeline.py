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

    async def fake_identity(client, handle):
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
    async def fake_identity(client, handle):
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

    async def fake_identity(client, handle):
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

    async def fake_identity(client, handle):
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
    async def fake_identity(client, handle):
        return {"identities": frozenset({"candidate"})}

    async def fake_repos(client, handle):
        return [{"full_name": "cand/missing", "clone_url": (tmp_path / "nope").as_uri()}]

    monkeypatch.setattr("veriquill.pipeline.fetch_identity", fake_identity)
    monkeypatch.setattr("veriquill.pipeline.list_repositories", fake_repos)

    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    summary = await analyse_candidate("cand", settings, client=FakeClient())

    assert summary.repositories[0].evidence is None

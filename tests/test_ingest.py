import httpx
import respx

from veriquill.config import Settings
from veriquill.github.client import GitHubClient
from veriquill.github.ingest import fetch_identity, list_repositories

BASE = "https://api.github.com"


@respx.mock
async def test_list_repositories_excludes_archived_but_keeps_forks(tmp_path):
    respx.get(f"{BASE}/users/octocat/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"full_name": "octocat/a", "fork": False, "archived": False},
                {"full_name": "octocat/b", "fork": True, "archived": False},
                {"full_name": "octocat/c", "fork": False, "archived": True},
            ],
        )
    )
    settings = Settings(github_token="t", data_dir=tmp_path)
    async with GitHubClient(settings) as client:
        repos = await list_repositories(client, "octocat")

    assert [r["full_name"] for r in repos] == ["octocat/a", "octocat/b"]


@respx.mock
async def test_fetch_identity_collects_known_identities(tmp_path):
    respx.get(f"{BASE}/users/octocat").mock(
        return_value=httpx.Response(
            200, json={"login": "octocat", "name": "Mona Cat", "email": "mona@example.com"}
        )
    )
    settings = Settings(github_token="t", data_dir=tmp_path)
    async with GitHubClient(settings) as client:
        identity = await fetch_identity(client, "octocat")

    assert "octocat" in identity["identities"]
    assert "mona@example.com" in identity["identities"]

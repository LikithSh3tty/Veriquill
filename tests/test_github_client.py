import httpx
import pytest
import respx

from veriquill.config import Settings
from veriquill.github.client import GitHubClient, MissingTokenError

BASE = "https://api.github.com"


def _settings(tmp_path, **kwargs) -> Settings:
    return Settings(github_token="test-token", data_dir=tmp_path, **kwargs)


@respx.mock
async def test_get_json_returns_payload_and_reads_quota(tmp_path):
    respx.get(f"{BASE}/users/octocat").mock(
        return_value=httpx.Response(
            200,
            json={"login": "octocat"},
            headers={"ETag": 'W/"v1"', "X-RateLimit-Remaining": "4999"},
        )
    )
    async with GitHubClient(_settings(tmp_path)) as client:
        payload = await client.get_json("/users/octocat")

    assert payload == {"login": "octocat"}
    assert client.remaining == 4999


@respx.mock
async def test_second_call_sends_if_none_match_and_serves_304_from_cache(tmp_path):
    settings = _settings(tmp_path)
    route = respx.get(f"{BASE}/users/octocat")
    route.side_effect = [
        httpx.Response(200, json={"login": "octocat"}, headers={"ETag": 'W/"v1"'}),
        httpx.Response(304, headers={"ETag": 'W/"v1"'}),
    ]

    async with GitHubClient(settings) as client:
        first = await client.get_json("/users/octocat")
    async with GitHubClient(settings) as client:
        second = await client.get_json("/users/octocat")

    assert first == second == {"login": "octocat"}
    assert route.calls[1].request.headers["If-None-Match"] == 'W/"v1"'


@respx.mock
async def test_secondary_rate_limit_is_retried_after_retry_after(tmp_path, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("veriquill.github.client.asyncio.sleep", fake_sleep)

    respx.get(f"{BASE}/users/octocat").side_effect = [
        httpx.Response(403, headers={"Retry-After": "2"}, json={"message": "slow down"}),
        httpx.Response(200, json={"login": "octocat"}),
    ]

    async with GitHubClient(_settings(tmp_path)) as client:
        payload = await client.get_json("/users/octocat")

    assert payload == {"login": "octocat"}
    assert slept == [2.0]


@respx.mock
async def test_pauses_when_remaining_quota_falls_below_floor(tmp_path, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("veriquill.github.client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("veriquill.github.client.time.time", lambda: 1000.0)

    respx.get(f"{BASE}/a").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "1030"},
        )
    )
    respx.get(f"{BASE}/b").mock(return_value=httpx.Response(200, json={"ok": True}))

    async with GitHubClient(_settings(tmp_path, rate_limit_floor=10)) as client:
        await client.get_json("/a")
        await client.get_json("/b")

    assert slept and slept[0] == pytest.approx(31.0)


async def test_missing_token_is_refused(tmp_path):
    with pytest.raises(MissingTokenError):
        async with GitHubClient(Settings(github_token="", data_dir=tmp_path)):
            pass


@respx.mock
async def test_paginate_follows_link_header(tmp_path):
    respx.get(f"{BASE}/users/octocat/repos", params={"per_page": "100"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"name": "one"}],
            headers={"Link": f'<{BASE}/users/octocat/repos?page=2>; rel="next"'},
        )
    )
    respx.get(f"{BASE}/users/octocat/repos", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"name": "two"}])
    )

    async with GitHubClient(_settings(tmp_path)) as client:
        items = await client.paginate("/users/octocat/repos")

    assert [i["name"] for i in items] == ["one", "two"]

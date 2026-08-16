"""Repository listing and identity resolution.

These are the only REST calls Veriquill makes per candidate: roughly two to
five, all ETag-cached, so a repeat run costs almost nothing.
"""

from __future__ import annotations

from typing import Any

from veriquill.github.client import GitHubClient


async def fetch_identity(client: GitHubClient, handle: str) -> dict[str, Any]:
    profile = await client.get_json(f"/users/{handle}")
    identities = {handle.lower()}
    for key in ("login", "name", "email"):
        value = profile.get(key)
        if value:
            identities.add(str(value).lower())
    user_id = profile.get("id")
    if user_id is not None:
        identities.add(f"{user_id}+{handle}@users.noreply.github.com".lower())
    identities.add(f"{handle}@users.noreply.github.com".lower())
    return {"profile": profile, "identities": frozenset(identities)}


async def list_repositories(client: GitHubClient, handle: str) -> list[dict[str, Any]]:
    """Forks are kept deliberately: the fork check needs to see them."""
    repos = await client.paginate(f"/users/{handle}/repos", params={"type": "owner"})
    return [repo for repo in repos if not repo.get("archived")]

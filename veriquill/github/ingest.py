"""Repository listing and identity resolution.

These are the only REST calls Veriquill makes per candidate: roughly two to
five, all ETag-cached, so a repeat run costs almost nothing.
"""

from __future__ import annotations

from typing import Any

from veriquill.github.client import GitHubClient


async def fetch_identity(
    client: GitHubClient, handle: str, aliases: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Resolve who this account is, including who it used to be.

    `aliases` carries names the candidate says are also theirs — a previous
    GitHub login, or the name their git config writes. Renames are common, and
    every commit pushed before one keeps the old login forever.
    """
    profile = await client.get_json(f"/users/{handle}")
    identities = {handle.lower()} | {a.strip().lower() for a in aliases if a.strip()}
    for key in ("login", "name", "email"):
        value = profile.get(key)
        if value:
            identities.add(str(value).lower())
    user_id = profile.get("id")
    if user_id is not None:
        identities.add(f"{user_id}+{handle}@users.noreply.github.com".lower())
    identities.add(f"{handle}@users.noreply.github.com".lower())
    for alias in list(identities):
        identities.add(f"{alias}@users.noreply.github.com")
    return {
        "profile": profile,
        "identities": frozenset(identities),
        "user_id": user_id,
    }


async def list_repositories(client: GitHubClient, handle: str) -> list[dict[str, Any]]:
    """Forks are kept deliberately: the fork check needs to see them."""
    repos = await client.paginate(f"/users/{handle}/repos", params={"type": "owner"})
    return [repo for repo in repos if not repo.get("archived")]

"""Repository listing and identity resolution.

These are the only REST calls Veriquill makes per candidate: roughly two to
five, all ETag-cached, so a repeat run costs almost nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from veriquill.github.client import GitHubClient

logger = logging.getLogger(__name__)


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


async def attributed_identities(
    client: GitHubClient, full_names: list[str], handle: str
) -> frozenset[str]:
    """The names and addresses GitHub itself attributes to this account.

    Every other identity here is a guess assembled from strings: the login, the
    profile's display name, the two noreply forms. That works only when the
    candidate's git config happens to write one of those, and a great many
    people sign commits with a personal address that is verified on the account
    but never public on the profile. TJ Holowaychuk's repositories read as zero
    of one thousand four hundred and twenty eight commits authored, on five
    repositories he wrote, because his commits say `tj@vision-media.ca` and his
    profile says `TJ`.

    GitHub already holds the mapping, because linking a commit to an account is
    what it does with a verified address. `?author=` asks for it directly, so
    this stops guessing and reads the answer.

    One page per repository is enough to learn how somebody signs their work;
    people have a handful of addresses, not a hundred. This is an identity
    lookup, not a census, and the commits themselves are counted from the clone.

    A failure here returns nothing rather than raising. Not learning an extra
    address leaves the previous guesses in place, which is where this started;
    letting the exception out would fail an analysis over an enrichment.
    """
    found: set[str] = set()

    for full_name in full_names:
        try:
            commits = await client.get_json(
                f"/repos/{full_name}/commits",
                params={"author": handle, "per_page": 100},
            )
        except Exception:  # an enrichment must never fail the analysis
            logger.info("cannot read attributed commits for %s", full_name, exc_info=True)
            continue

        if not isinstance(commits, list):
            continue

        for entry in commits:
            # Only entries GitHub itself linked to this account. An unlinked
            # commit is the guesswork this exists to replace.
            author = entry.get("author") or {}
            if str(author.get("login", "")).lower() != handle.lower():
                continue
            signature = (entry.get("commit") or {}).get("author") or {}
            for key in ("name", "email"):
                value = signature.get(key)
                if value:
                    found.add(str(value).lower())

    return frozenset(found)

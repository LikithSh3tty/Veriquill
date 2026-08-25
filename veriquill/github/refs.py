"""What a repository's history currently is, without cloning it.

Re-analysing a candidate re-clones every repository and walks it again, which
is minutes of work to reach a dossier that is very often identical to the one
already stored. `git ls-remote` answers the only question that matters first:
has anything moved.

**The invalidation rule is the whole design, so it is stated here rather than
assumed.** A commit sha covers its entire ancestry, so two histories with the
same head sha are the same history. That makes a fingerprint over every ref
sound against exactly the thing this tool exists to notice: a force-push, a
rebase, a squash, an amended root commit, all of them change some sha. A
deleted or added branch changes the set, which is why refs are named as well as
hashed rather than the shas being summed.

The tool's own version is folded in. A dossier is only reusable if the code
that would produce it again is the code that produced it, and a new check has
to re-read a repository that has not changed.

Nothing here executes anything from the repository. `ls-remote` talks to the
remote and touches no working tree.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os

from veriquill import __version__

logger = logging.getLogger(__name__)


class RefsUnavailable(RuntimeError):
    """Raised when the remote could not be asked what it holds."""


async def read_refs(clone_url: str, timeout: int) -> dict[str, str]:
    """Every ref the remote advertises, as {name: sha}."""
    process = await asyncio.create_subprocess_exec(
        "git",
        "ls-remote",
        "--quiet",
        clone_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        raise RefsUnavailable(f"ls-remote of {clone_url} timed out after {timeout}s") from None

    if process.returncode != 0:
        raise RefsUnavailable(
            f"ls-remote of {clone_url} failed: {stderr.decode('utf-8', 'replace').strip()}"
        )

    refs: dict[str, str] = {}
    for line in stdout.decode("utf-8", "replace").splitlines():
        sha, _, name = line.partition("\t")
        if sha and name:
            refs[name.strip()] = sha.strip()
    return refs


def fingerprint(refs_by_repo: dict[str, dict[str, str]]) -> str:
    """A single value that changes whenever any history does.

    Refs are named as well as hashed, so deleting a branch is a change even
    though no sha was rewritten. The tool version is folded in so a dossier is
    only reused by the code that produced it.
    """
    digest = hashlib.sha256()
    digest.update(__version__.encode("utf-8"))
    for repo in sorted(refs_by_repo):
        digest.update(b"\x00")
        digest.update(repo.encode("utf-8"))
        for name in sorted(refs_by_repo[repo]):
            digest.update(b"\x01")
            digest.update(name.encode("utf-8"))
            digest.update(b"\x02")
            digest.update(refs_by_repo[repo][name].encode("utf-8"))
    return digest.hexdigest()


async def account_fingerprint(clone_urls: dict[str, str], timeout: int) -> str | None:
    """Fingerprint every repository about to be read, or None if any refuses.

    None means the question could not be answered, and an unanswered question
    is never treated as "nothing changed". A repository that has gone private
    or a remote that is down both land here, and both should re-analyse rather
    than serve a stale dossier as though it were fresh.
    """
    refs_by_repo: dict[str, dict[str, str]] = {}

    for full_name, url in sorted(clone_urls.items()):
        try:
            refs_by_repo[full_name] = await read_refs(url, timeout)
        except RefsUnavailable as exc:
            logger.info("cannot fingerprint %s, so it will be re-read: %s", full_name, exc)
            return None

    return fingerprint(refs_by_repo)

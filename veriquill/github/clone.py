"""Ephemeral clones.

Clones are complete on purpose. `--filter=blob:none` looks like the cheaper
choice and is actively wrong for this workload: provenance reads history with
`git log --numstat`, which computes diffs, which needs blob contents. Against a
partial clone git back-fills those blobs from the remote one round trip at a
time, so a repository that clones in 19 seconds takes hours to analyse. A full
clone pays once, in a single packfile transfer.

Git transport is not billed against the REST hourly quota either way.

The timeout here is load-bearing. A single large repository must never be able
to stall a candidate's whole run, so the wait, the kill, and the cleanup all
have to work on every platform Veriquill runs on.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
from uuid import uuid4

GIT_BINARY = "git"


class CloneError(RuntimeError):
    pass


def _force_remove(func: Any, path: str, _exc_info: Any) -> None:
    """Clear the read-only bit and retry.

    Git marks objects in `.git` read-only, and on Windows that makes unlink
    fail outright, so a plain rmtree leaves clone directories behind.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, onerror=_force_remove)


async def _terminate_tree(process: asyncio.subprocess.Process) -> None:
    """Kill the clone and everything it spawned.

    `git clone` delegates the transfer to a `git-remote-https` child. Killing
    only the parent leaves that child downloading indefinitely, so on Windows
    the whole tree has to go via taskkill.
    """
    if process.returncode is not None:
        return

    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(process.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        except OSError:
            pass
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass

    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except (TimeoutError, ProcessLookupError):
        pass


async def clone_repo(clone_url: str, dest: Path, timeout: int) -> Path:
    """Clone `clone_url` into `dest`, or raise `CloneError` within `timeout`.

    Output goes to a file rather than a pipe on purpose. Wrapping
    `process.communicate()` in `wait_for` deadlocks on Windows: cancelling a
    pending overlapped pipe read does not complete until the pipe closes, and
    the pipe does not close while git still holds it, so the timeout never
    fires and the kill is never reached.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    log_path = dest.parent / f"{dest.name}.clone.log"

    try:
        with log_path.open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                GIT_BINARY,
                "clone",
                "--quiet",
                clone_url,
                str(dest),
                stdout=log,
                stderr=log,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            try:
                returncode = await asyncio.wait_for(process.wait(), timeout=timeout)
            except TimeoutError as exc:
                await _terminate_tree(process)
                raise CloneError(
                    f"clone of {clone_url} timed out after {timeout}s"
                ) from exc

        if returncode != 0:
            detail = _read_log(log_path)
            raise CloneError(f"clone of {clone_url} failed: {detail}")
    finally:
        log_path.unlink(missing_ok=True)

    return dest


def _read_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace").strip()[:500]
    except OSError:
        return "no output captured"


@asynccontextmanager
async def ephemeral_clone(
    clone_url: str, workdir: Path, timeout: int
) -> AsyncIterator[Path]:
    dest = workdir / uuid4().hex
    try:
        yield await clone_repo(clone_url, dest, timeout)
    finally:
        remove_tree(dest)


#: How old an abandoned clone must be before it is reclaimed. Far longer than
#: any analysis takes, because the only thing that must never happen here is
#: deleting the working copy of a run that is still going.
STALE_CLONE_SECONDS = 6 * 60 * 60


def sweep_workdir(workdir: Path, older_than: float = STALE_CLONE_SECONDS) -> int:
    """Reclaim clones left behind by runs that did not get to clean up.

    `ephemeral_clone` deletes its directory in a `finally`, which covers an
    exception and does nothing at all for a killed process. Nothing else ever
    looked at the working directory, so every interrupted analysis left a full
    clone of every repository it had reached, permanently. Five of them were
    sitting in this project's working directory, from runs against real
    accounts that were interrupted, on a disk that had reached ninety seven
    percent full.

    Age is the only signal available, since the directory names are random and
    carry no owner. The threshold is deliberately far past any real analysis so
    that a long run in another process is never the thing that gets deleted.

    Returns how many were removed. Failures are counted as survivors rather
    than raised: a directory that cannot be removed is a housekeeping problem,
    not a reason to refuse to analyse anything.
    """
    if not workdir.is_dir():
        return 0

    cutoff = time.time() - older_than
    removed = 0

    for entry in workdir.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime > cutoff:
                continue
            remove_tree(entry)
            removed += 1
        except OSError:
            logger.info("could not reclaim abandoned clone %s", entry, exc_info=True)

    if removed:
        logger.info("reclaimed %d abandoned clone(s) from %s", removed, workdir)
    return removed

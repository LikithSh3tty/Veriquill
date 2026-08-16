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
import os
import shutil
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
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
    except (asyncio.TimeoutError, ProcessLookupError):
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
            except asyncio.TimeoutError as exc:
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

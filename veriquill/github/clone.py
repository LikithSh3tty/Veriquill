"""Ephemeral clones.

`--filter=blob:none` fetches the full commit graph immediately and defers file
blobs until something reads them, which keeps large portfolios cheap. Git
transport is not billed against the REST hourly quota.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4


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


async def clone_repo(clone_url: str, dest: Path, timeout: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        "git",
        "clone",
        "--filter=blob:none",
        "--quiet",
        clone_url,
        str(dest),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        raise CloneError(f"clone of {clone_url} timed out after {timeout}s") from exc

    if process.returncode != 0:
        raise CloneError(
            f"clone of {clone_url} failed: {stderr.decode(errors='replace').strip()}"
        )
    return dest


@asynccontextmanager
async def ephemeral_clone(
    clone_url: str, workdir: Path, timeout: int
) -> AsyncIterator[Path]:
    dest = workdir / uuid4().hex
    try:
        yield await clone_repo(clone_url, dest, timeout)
    finally:
        remove_tree(dest)

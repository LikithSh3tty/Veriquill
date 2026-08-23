"""Running an external analyser over authored files, and nothing else.

Two rules, both learned the hard way by pointing a tool at a repository root
and believing what came back.

**Name the files, do not name the directory.** `vendored.py` opens by saying
that every metric excludes vendored and generated paths. That was true of every
analyser that walked `profile.python_files` and false of the two that took a
path and recursed it themselves. Bandit reported four security findings against
a candidate whose only authored file was clean, every one of them inside
`node_modules`. A tool that exists to separate what a candidate wrote from what
they acquired cannot then charge them for the latter.

**Command lines are finite.** Naming files instead of a directory means a large
repository can exceed what the platform will accept, so arguments are batched
and the results concatenated. The batches are sized well under the Windows limit
because that is the smallest of the three platforms this runs on.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Characters of file arguments per invocation. Windows caps a command line at
#: about 32,000; this leaves generous room for the executable and its flags.
ARG_BUDGET = 24_000


def batches(paths: list[Path], budget: int = ARG_BUDGET) -> Iterator[list[str]]:
    """Group paths into invocations no command line will refuse.

    A single path longer than the budget still gets its own batch: refusing to
    analyse it would silently drop a file, and letting the platform reject the
    call is at least visible.
    """
    current: list[str] = []
    size = 0

    for path in paths:
        text = str(path)
        if current and size + len(text) + 1 > budget:
            yield current
            current, size = [], 0
        current.append(text)
        size += len(text) + 1

    if current:
        yield current


def run_json(argv: list[str], paths: list[Path], timeout: int) -> list[Any]:
    """Run `argv` over `paths` in batches, returning each batch's parsed stdout.

    A batch that times out, fails to start, or returns something that is not
    JSON contributes nothing rather than failing the run. An analyser that
    cannot speak is a gap in coverage, and coverage is reported separately; it
    is never a finding against the candidate.
    """
    parsed: list[Any] = []

    for batch in batches(paths):
        try:
            result = subprocess.run(
                [*argv, *batch],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            logger.info("%s did not complete over %d file(s)", argv[2:4], len(batch))
            continue

        try:
            parsed.append(json.loads(result.stdout or "null"))
        except json.JSONDecodeError:
            logger.info("%s returned output that was not JSON", argv[2:4])

    return parsed


def python_tool(module: str, *flags: str) -> list[str]:
    """Invoke a tool through this interpreter, not through whatever is on PATH.

    The candidate's repository is on disk and may contain an executable with a
    matching name. Going through `sys.executable -m` runs the copy that was
    installed with Veriquill.
    """
    return [sys.executable, "-m", module, *flags]

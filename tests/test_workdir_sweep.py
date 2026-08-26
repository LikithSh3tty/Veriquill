"""Clones left behind by a run that was killed have to be reclaimed by the next one.

`ephemeral_clone` removes its directory in a `finally`, which covers an
exception and does nothing whatsoever for a killed process. Nothing else looked
at the working directory, so every interrupted analysis left a full clone of
every repository it had reached, for good. Five were found in this project's
working directory, left by interrupted runs against real accounts, on a disk
that had reached 97% full.
"""

from __future__ import annotations

import os
import time

from veriquill.github.clone import STALE_CLONE_SECONDS, sweep_workdir


def _clone_dir(workdir, name: str, age_seconds: float):
    path = workdir / name
    path.mkdir(parents=True)
    (path / ".git").mkdir()
    (path / "main.py").write_text("print('hi')", encoding="utf-8")
    when = time.time() - age_seconds
    os.utime(path, (when, when))
    return path


def test_an_abandoned_clone_is_reclaimed(tmp_path):
    stale = _clone_dir(tmp_path, "abandoned", STALE_CLONE_SECONDS + 60)

    assert sweep_workdir(tmp_path) == 1
    assert not stale.exists()


def test_a_clone_a_running_analysis_might_own_is_left_alone(tmp_path):
    """Age is the only signal, so the threshold has to sit far past any real run."""
    fresh = _clone_dir(tmp_path, "in-flight", 60)

    assert sweep_workdir(tmp_path) == 0
    assert fresh.exists()


def test_the_threshold_is_far_longer_than_an_analysis(tmp_path):
    """A clone timeout is measured in minutes; deleting a live run would be worse."""
    assert STALE_CLONE_SECONDS >= 6 * 60 * 60


def test_a_missing_working_directory_is_not_an_error(tmp_path):
    assert sweep_workdir(tmp_path / "never-created") == 0


def test_a_loose_file_is_not_mistaken_for_a_clone(tmp_path):
    stray = tmp_path / "notes.txt"
    stray.write_text("kept", encoding="utf-8")
    when = time.time() - STALE_CLONE_SECONDS * 2
    os.utime(stray, (when, when))

    assert sweep_workdir(tmp_path) == 0
    assert stray.exists()

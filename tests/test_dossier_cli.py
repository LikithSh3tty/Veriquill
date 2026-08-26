"""The dossier command, run the way a person runs it.

Every other test of this path calls the functions underneath directly, which is
why the command spent a release doing the entire analysis and then throwing it
away on its last line: the record it printed the id of had been detached by the
commit two lines earlier. Nothing that skips the command could see that.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from veriquill.cli import app
from veriquill.config import Settings, get_settings
from veriquill.pipeline import RunSummary

runner = CliRunner()


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(github_token="t", data_dir=tmp_path / ".veriquill")
    monkeypatch.setattr("veriquill.cli.get_settings", lambda: settings)

    async def fake_analysis(handle, config, aliases=frozenset(), **kwargs):
        return RunSummary(handle=handle, started_at=datetime.now(UTC), repositories=[])

    monkeypatch.setattr("veriquill.cli.analyse_candidate", fake_analysis)
    yield settings
    get_settings.cache_clear()


def test_dossier_prints_the_report_it_just_stored(workspace):
    result = runner.invoke(app, ["dossier", "cand"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["handle"] == "cand"


def test_dossier_names_the_stored_id_a_comparison_would_use(workspace):
    result = runner.invoke(app, ["dossier", "cand"])

    assert result.exit_code == 0, result.output
    # The id is the whole point of the line: ranking reads dossiers by it, so a
    # message that cannot name one leaves the operator with nothing to pass on.
    assert "stored dossier 1 for cand" in result.stderr


def test_dossier_writes_the_file_it_was_asked_for(workspace, tmp_path):
    out = tmp_path / "cand.json"
    result = runner.invoke(app, ["dossier", "cand", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["handle"] == "cand"

"""The CLI is the surface a recruiter actually touches; its refusals matter."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tests.test_dimensions import flag, make_dossier
from veriquill.cli import app
from veriquill.config import Settings, get_settings
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.rubric import DIMENSIONS
from veriquill.store import save_dossier

runner = CliRunner()


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(data_dir=tmp_path / ".veriquill")
    monkeypatch.setattr("veriquill.cli.get_settings", lambda: settings)

    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        for handle in ("alpha", "beta"):
            payload = make_dossier(
                red_flag_register=[flag("provenance.bulk_dump", "critical", flag_id="abc")]
            )
            payload["handle"] = handle
            save_dossier(session, payload)
        session.commit()

    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(
        json.dumps({"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}}),
        encoding="utf-8",
    )
    yield rubric_path
    get_settings.cache_clear()


def run(*args):
    return runner.invoke(app, list(args))


def test_rubric_add_then_list(workspace):
    assert run("rubric-add", str(workspace)).exit_code == 0

    listed = run("rubric-list")

    assert listed.exit_code == 0
    assert "backend" in listed.stdout


def test_rank_prints_a_comparison_id_and_an_ordering(workspace):
    run("rubric-add", str(workspace))

    result = run("rank", "--rubric", "backend", "--candidate", "alpha", "--candidate", "beta")

    assert result.exit_code == 0
    assert "comparison" in result.stdout.lower()
    assert "alpha" in result.stdout


def test_rank_refuses_an_unknown_candidate(workspace):
    run("rubric-add", str(workspace))

    result = run("rank", "--rubric", "backend", "--candidate", "ghost")

    assert result.exit_code != 0
    assert "ghost" in result.stdout


def test_export_is_refused_before_approval(workspace, tmp_path):
    run("rubric-add", str(workspace))
    run("rank", "--rubric", "backend", "--candidate", "alpha")

    result = run("export-comparison", "1", "--output", str(tmp_path / "out.json"))

    assert result.exit_code != 0
    assert "pending" in result.stdout.lower()


def test_dismiss_then_approve_then_export(workspace, tmp_path):
    run("rubric-add", str(workspace))
    run("rank", "--rubric", "backend", "--candidate", "alpha")

    dismissed = run(
        "review-flag",
        "1",
        "--candidate",
        "alpha",
        "--flag",
        "abc",
        "--action",
        "dismiss",
        "--actor",
        "reviewer",
        "--reason",
        "employer-owned import",
    )
    approved = run("review-approve", "1", "--actor", "reviewer")
    out = tmp_path / "out.json"
    exported = run("export-comparison", "1", "--output", str(out))

    assert dismissed.exit_code == 0
    assert approved.exit_code == 0
    assert exported.exit_code == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "reviewed"
    assert payload["audit_log"][0]["reason"] == "employer-owned import"


def test_review_flag_requires_a_reason(workspace):
    run("rubric-add", str(workspace))
    run("rank", "--rubric", "backend", "--candidate", "alpha")

    result = run(
        "review-flag",
        "1",
        "--candidate",
        "alpha",
        "--flag",
        "abc",
        "--action",
        "dismiss",
        "--actor",
        "reviewer",
        "--reason",
        "  ",
    )

    assert result.exit_code != 0
    assert "reason" in result.stdout.lower()


def test_review_show_lists_flags_with_their_ids(workspace):
    run("rubric-add", str(workspace))
    run("rank", "--rubric", "backend", "--candidate", "alpha")

    result = run("review-show", "1")

    assert result.exit_code == 0
    assert "abc" in result.stdout


def test_a_dossier_file_can_be_imported_and_then_ranked(workspace, tmp_path):
    run("rubric-add", str(workspace))

    payload = make_dossier()
    payload["handle"] = "gamma"
    path = tmp_path / "gamma.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    imported = run("dossier-import", str(path))
    ranked = run("rank", "--rubric", "backend", "--candidate", "gamma")

    assert imported.exit_code == 0
    assert "gamma" in imported.stdout
    assert ranked.exit_code == 0
    assert "gamma" in ranked.stdout


def test_importing_a_dossier_without_a_handle_is_refused(workspace, tmp_path):
    path = tmp_path / "headless.json"
    path.write_text(json.dumps({"red_flag_register": []}), encoding="utf-8")

    result = run("dossier-import", str(path))

    assert result.exit_code != 0
    assert "handle" in result.stdout


def test_audit_prints_every_action(workspace):
    run("rubric-add", str(workspace))
    run("rank", "--rubric", "backend", "--candidate", "alpha")
    run("review-approve", "1", "--actor", "reviewer")

    result = run("audit", "1")

    assert result.exit_code == 0
    assert "approve" in result.stdout

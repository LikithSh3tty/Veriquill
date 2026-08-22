from datetime import datetime, timezone

from fastapi.testclient import TestClient

from veriquill.api.main import app
from veriquill.pipeline import RepoResult, RunSummary


async def _fake_analyse(handle, settings, client=None, known_fingerprints=None):
    return RunSummary(
        handle=handle,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        repositories=[RepoResult(full_name=f'{handle}/demo')],
    )


def _isolated_client(tmp_path, monkeypatch):
    """An API client pointed at a temporary database of its own.

    Run summaries are stored now, so a test that starts one would otherwise
    write into whatever database the working directory happens to hold.
    """
    from veriquill.api import main as api_main
    from veriquill.config import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings(data_dir=tmp_path / '.veriquill')
    monkeypatch.setattr(api_main, 'get_settings', lambda: settings)
    settings.ensure_dirs()
    return TestClient(app)


def test_health_reports_version():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyse_starts_a_run_and_run_is_retrievable(tmp_path, monkeypatch):
    monkeypatch.setattr("veriquill.api.main.analyse_candidate", _fake_analyse)
    client = _isolated_client(tmp_path, monkeypatch)
    started = client.post("/analyse", json={"handle": "octocat"})
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    fetched = client.get(f"/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["handle"] == "octocat"


def test_unknown_run_returns_404(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    assert client.get("/runs/does-not-exist").status_code == 404


def test_a_run_summary_survives_a_restart(tmp_path, monkeypatch):
    """The reason to persist: a completed analysis must not become a 404."""
    monkeypatch.setattr("veriquill.api.main.analyse_candidate", _fake_analyse)
    client = _isolated_client(tmp_path, monkeypatch)
    run_id = client.post("/analyse", json={"handle": "octocat"}).json()["run_id"]

    # A fresh client over the same database is what a restart looks like here.
    restarted = TestClient(app)
    fetched = restarted.get(f"/runs/{run_id}")

    assert fetched.status_code == 200
    assert fetched.json()["summary"]["handle"] == "octocat"


def test_the_same_api_answers_under_the_prefix_the_browser_bundle_uses():
    """The built interface calls /api/... on its own origin. Serving it from
    anywhere else would need a second host and a CORS policy to match."""
    client = TestClient(app)
    root = client.get("/health")
    prefixed = client.get("/api/health")
    assert prefixed.status_code == 200
    assert prefixed.json() == root.json()


def test_the_prefixed_copy_stays_out_of_the_schema():
    """One surface, documented once: a reader should not have to guess which of
    two identical paths is the real one."""
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    assert "/health" in paths
    assert not [path for path in paths if path.startswith("/api/")]


def _seeded_client(tmp_path, monkeypatch, flagged=True):
    """An API client pointed at a temporary database holding one stored dossier."""
    from tests.test_dimensions import flag, make_dossier
    from veriquill.api import main as api_main
    from veriquill.config import Settings, get_settings
    from veriquill.db import init_db, make_engine, make_session_factory
    from veriquill.store import save_dossier

    get_settings.cache_clear()
    settings = Settings(data_dir=tmp_path / ".veriquill")
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    settings.ensure_dirs()

    engine = make_engine(settings.db_path)
    init_db(engine)
    with make_session_factory(engine)() as session:
        register = (
            [flag("provenance.bulk_dump", "critical", flag_id="abc")] if flagged else []
        )
        payload = make_dossier(red_flag_register=register)
        payload["handle"] = "alpha"
        save_dossier(session, payload)
        session.commit()

    return TestClient(api_main.app)


def test_rubric_and_comparison_lifecycle_over_http(tmp_path, monkeypatch):
    from veriquill.config import get_settings
    from veriquill.rubric import DIMENSIONS

    client = _seeded_client(tmp_path, monkeypatch)

    created = client.post(
        "/rubrics", json={"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}}
    )
    assert created.status_code == 200

    comparison = client.post(
        "/comparisons", json={"rubric": "backend", "candidates": ["alpha"]}
    )
    assert comparison.status_code == 200
    comparison_id = comparison.json()["comparison_id"]

    pending = client.get(f"/comparisons/{comparison_id}/export")
    assert pending.status_code == 409

    reviewed = client.post(
        f"/comparisons/{comparison_id}/review",
        json={
            "actor": "reviewer",
            "action": "flag_dismiss",
            "candidate": "alpha",
            "target": "abc",
            "reason": "employer-owned import",
        },
    )
    assert reviewed.status_code == 200

    approved = client.post(
        f"/comparisons/{comparison_id}/approve", json={"actor": "reviewer"}
    )
    assert approved.status_code == 200

    exported = client.get(f"/comparisons/{comparison_id}/export")
    assert exported.status_code == 200
    assert exported.json()["status"] == "reviewed"

    audit = client.get(f"/comparisons/{comparison_id}/audit")
    assert [row["action"] for row in audit.json()["audit_log"]] == [
        "flag_dismiss",
        "approve",
    ]

    get_settings.cache_clear()


def test_a_review_action_without_a_reason_is_rejected(tmp_path, monkeypatch):
    from veriquill.config import get_settings
    from veriquill.rubric import DIMENSIONS

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    client.post("/rubrics", json={"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})
    created = client.post("/comparisons", json={"rubric": "backend", "candidates": ["alpha"]})
    comparison_id = created.json()["comparison_id"]

    response = client.post(
        f"/comparisons/{comparison_id}/review",
        json={
            "actor": "reviewer",
            "action": "band_override",
            "candidate": "alpha",
            "target": "strong hire",
            "reason": "",
        },
    )

    assert response.status_code == 400
    assert "reason" in response.json()["detail"]

    get_settings.cache_clear()


def test_an_unknown_rubric_is_a_400_not_a_crash(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    response = client.post("/comparisons", json={"rubric": "ghost", "candidates": ["alpha"]})

    assert response.status_code == 400
    assert "ghost" in response.json()["detail"]

    get_settings.cache_clear()


def test_a_comparison_exposes_the_red_flags_a_reviewer_must_act_on(tmp_path, monkeypatch):
    """The review screen dismisses flags by id, so it has to be able to read them."""
    from veriquill.config import get_settings
    from veriquill.rubric import DIMENSIONS

    client = _seeded_client(tmp_path, monkeypatch)

    client.post("/rubrics", json={"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})
    created = client.post("/comparisons", json={"rubric": "backend", "candidates": ["alpha"]})
    comparison_id = created.json()["comparison_id"]

    response = client.get(f"/comparisons/{comparison_id}/dossiers")

    assert response.status_code == 200
    flags = response.json()["dossiers"]["alpha"]["red_flag_register"]
    assert flags[0]["flag_id"] == "abc"
    assert flags[0]["evidence"]

    get_settings.cache_clear()


def test_dossiers_for_an_unknown_comparison_are_a_404(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    assert client.get("/comparisons/404/dossiers").status_code == 404

    get_settings.cache_clear()


def test_candidates_can_be_added_from_the_interface(tmp_path, monkeypatch):
    """The whole point of intake: a handle goes in, a stored dossier comes out."""
    from veriquill.api import main as api_main
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    async def fake_pipeline(handle, settings, resume=None, linkedin=None, job_description=""):
        from tests.test_dimensions import make_dossier

        payload = make_dossier()
        payload["handle"] = handle
        return payload

    monkeypatch.setattr(api_main, "build_candidate_dossier", fake_pipeline)

    accepted = client.post("/candidates", data={"handle": "newcomer"})
    assert accepted.status_code == 202
    job_id = accepted.json()["job"]["id"]

    # TestClient runs background tasks before returning, so the job is settled.
    job = client.get(f"/candidates/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["job"]["status"] == "done"
    assert job.json()["job"]["dossier_id"]

    listed = client.get("/candidates")
    assert "newcomer" in [row["handle"] for row in listed.json()["candidates"]]

    get_settings.cache_clear()


def test_a_failed_analysis_reports_why_rather_than_vanishing(tmp_path, monkeypatch):
    from veriquill.api import main as api_main
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    async def explode(handle, settings, resume=None, linkedin=None, job_description=""):
        raise RuntimeError("GitHub said 404 for 'ghost'")

    monkeypatch.setattr(api_main, "build_candidate_dossier", explode)

    accepted = client.post("/candidates", data={"handle": "ghost"})
    job_id = accepted.json()["job"]["id"]

    job = client.get(f"/candidates/jobs/{job_id}").json()["job"]
    assert job["status"] == "failed"
    assert "404" in job["error"]

    get_settings.cache_clear()


def test_a_malformed_handle_is_refused_before_any_work_starts(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    response = client.post("/candidates", data={"handle": "not a handle"})

    assert response.status_code == 400
    assert "GitHub username" in response.json()["detail"]

    get_settings.cache_clear()


def test_an_unsupported_upload_is_refused(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    response = client.post(
        "/candidates",
        data={"handle": "octocat"},
        files={"resume": ("payload.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert ".exe" in response.json()["detail"]

    get_settings.cache_clear()


def test_an_unknown_job_is_a_404(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    assert client.get("/candidates/jobs/nope").status_code == 404

    get_settings.cache_clear()


def test_a_job_description_becomes_a_rubric(tmp_path, monkeypatch):
    """A recruiter has a posting, not a weights table."""
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    response = client.post(
        "/rubrics/from-job-description",
        json={
            "name": "secure-backend",
            "text": "You will write unit tests and practise secure coding against OWASP.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rubric"]["name"] == "secure-backend"
    assert body["derivation"]["emphases"]["security"]
    assert body["derivation"]["emphases"]["test_quality"]

    # It is stored, so a comparison can be created against it straight away.
    listed = client.get("/rubrics").json()["rubrics"]
    assert "secure-backend" in [r["name"] for r in listed]

    get_settings.cache_clear()


def test_an_empty_job_description_is_refused(tmp_path, monkeypatch):
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)

    response = client.post(
        "/rubrics/from-job-description", json={"name": "empty", "text": "   "}
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]

    get_settings.cache_clear()


def test_a_posting_supplied_at_intake_reaches_the_analysis(tmp_path, monkeypatch):
    """A large account is read most-relevant-first, so the posting has to arrive
    before any cloning starts."""
    from veriquill.api import main as api_main
    from veriquill.config import get_settings

    client = _seeded_client(tmp_path, monkeypatch, flagged=False)
    seen = {}

    async def capture(handle, settings, resume=None, linkedin=None, job_description=""):
        from tests.test_dimensions import make_dossier

        seen["job_description"] = job_description
        payload = make_dossier()
        payload["handle"] = handle
        return payload

    monkeypatch.setattr(api_main, "build_candidate_dossier", capture)

    client.post(
        "/candidates",
        data={"handle": "newcomer", "job_description": "Python and OWASP."},
    )

    assert seen["job_description"] == "Python and OWASP."

    get_settings.cache_clear()

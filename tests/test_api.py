from datetime import datetime, timezone

from fastapi.testclient import TestClient

from veriquill.api.main import _RUNS, app
from veriquill.pipeline import RepoResult, RunSummary


def test_health_reports_version():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyse_starts_a_run_and_run_is_retrievable(monkeypatch):
    async def fake_analyse(handle, settings, client=None, known_fingerprints=None):
        return RunSummary(
            handle=handle,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            repositories=[RepoResult(full_name=f"{handle}/demo")],
        )

    monkeypatch.setattr("veriquill.api.main.analyse_candidate", fake_analyse)
    _RUNS.clear()

    client = TestClient(app)
    started = client.post("/analyse", json={"handle": "octocat"})
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    fetched = client.get(f"/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["handle"] == "octocat"


def test_unknown_run_returns_404():
    client = TestClient(app)
    assert client.get("/runs/does-not-exist").status_code == 404

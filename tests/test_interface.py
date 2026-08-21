"""Serving the built interface beside the API it calls."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from veriquill.api.interface import mount_interface


def _built(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>landing</html>", encoding="utf-8")
    (dist / "review.html").write_text("<html>review</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def _app():
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_an_unbuilt_checkout_still_serves_the_api(tmp_path):
    """The CLI and the tests use the API without ever loading a page, so a
    missing build cannot stop the process starting."""
    app = _app()
    assert mount_interface(app, tmp_path / "never-built") is False
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_the_root_serves_the_public_page(tmp_path):
    app = _app()
    assert mount_interface(app, _built(tmp_path)) is True
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "landing" in response.text


def test_the_review_screen_is_served_at_the_path_the_public_page_links_to(tmp_path):
    """The landing page links to /review.html. Serving it anywhere else breaks
    the one route a recruiter actually follows."""
    app = _app()
    mount_interface(app, _built(tmp_path))
    client = TestClient(app)
    assert "review" in client.get("/review.html").text
    assert client.get("/assets/app.js").status_code == 200


def test_the_api_still_answers_from_behind_the_mount(tmp_path):
    """The mount sits at the root. It must catch what is left over, not shadow
    routes registered before it."""
    app = _app()
    mount_interface(app, _built(tmp_path))
    assert TestClient(app).get("/health").json() == {"status": "ok"}

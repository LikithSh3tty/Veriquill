"""Caps on an API that has no authentication in front of it.

Every endpoint here is reachable by anyone who can reach the host. That is a
deployment decision recorded elsewhere; what it means for this layer is that a
caller must not be able to spend the process's memory or start unbounded work.
These are the floor beneath authentication, not a replacement for it.
"""

from __future__ import annotations

import io

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from veriquill.api.limits import (
    BodySizeLimitMiddleware,
    FixedWindowLimiter,
    LimitExceeded,
    read_capped,
)


class _Upload:
    """The slice of UploadFile that read_capped uses."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


async def test_an_upload_within_the_limit_is_read_whole():
    payload = b"x" * 1024

    read = await read_capped(_Upload(payload), limit=4096, label="resume")

    assert read == payload


async def test_an_oversized_upload_is_refused():
    with pytest.raises(LimitExceeded) as exc:
        await read_capped(_Upload(b"x" * 8192), limit=4096, label="resume")

    assert exc.value.status_code == 413
    assert "resume" in exc.value.detail


async def test_an_oversized_upload_is_refused_without_buffering_it_whole():
    """The point of the cap: memory is not spent before the size is known."""

    class Counting(_Upload):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.bytes_read = 0

        async def read(self, size: int = -1) -> bytes:
            chunk = await super().read(size)
            self.bytes_read += len(chunk)
            return chunk

    upload = Counting(b"x" * (5 * 1024 * 1024))

    with pytest.raises(LimitExceeded):
        await read_capped(upload, limit=64 * 1024, label="resume")

    assert upload.bytes_read < 5 * 1024 * 1024


def _app(max_bytes: int = 1024) -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo(request: Request) -> dict:
        return {"length": len(await request.body())}

    return app


def test_a_declared_oversized_body_is_refused():
    client = TestClient(_app())

    response = client.post("/echo", content=b"x" * 4096)

    assert response.status_code == 413


def test_a_body_within_the_limit_reaches_the_handler():
    client = TestClient(_app())

    response = client.post("/echo", content=b"x" * 512)

    assert response.status_code == 200
    assert response.json()["length"] == 512


def test_an_undeclared_oversized_body_is_refused_too():
    """A client that omits Content-Length must not walk past the cap."""
    client = TestClient(_app())

    def chunks():
        for _ in range(8):
            yield b"x" * 512

    response = client.post("/echo", content=chunks())

    assert response.status_code == 413


def test_an_undeclared_body_within_the_limit_still_reaches_the_handler():
    client = TestClient(_app())

    def chunks():
        for _ in range(2):
            yield b"x" * 128

    response = client.post("/echo", content=chunks())

    assert response.status_code == 200
    assert response.json()["length"] == 256


def test_a_caller_within_budget_is_allowed():
    limiter = FixedWindowLimiter(limit=3, window_seconds=60)

    for _ in range(3):
        limiter.check("1.2.3.4", now=100.0)


def test_a_caller_over_budget_is_refused():
    limiter = FixedWindowLimiter(limit=2, window_seconds=60)
    limiter.check("1.2.3.4", now=100.0)
    limiter.check("1.2.3.4", now=100.0)

    with pytest.raises(LimitExceeded) as exc:
        limiter.check("1.2.3.4", now=100.0)

    assert exc.value.status_code == 429


def test_the_budget_refills_once_the_window_passes():
    limiter = FixedWindowLimiter(limit=1, window_seconds=60)
    limiter.check("1.2.3.4", now=100.0)

    with pytest.raises(LimitExceeded):
        limiter.check("1.2.3.4", now=110.0)

    limiter.check("1.2.3.4", now=161.0)


def test_one_caller_cannot_spend_another_callers_budget():
    limiter = FixedWindowLimiter(limit=1, window_seconds=60)
    limiter.check("1.2.3.4", now=100.0)

    limiter.check("5.6.7.8", now=100.0)


def test_a_zero_limit_disables_the_limiter():
    """So a deployment behind its own gateway can turn this off deliberately."""
    limiter = FixedWindowLimiter(limit=0, window_seconds=60)

    for _ in range(100):
        limiter.check("1.2.3.4", now=100.0)


def _api_client() -> TestClient:
    from veriquill.api.main import app

    return TestClient(app)


def test_the_app_refuses_an_oversized_job_description():
    """The cap is wired into the route, not only available to it."""
    from veriquill.config import get_settings

    limit = get_settings().max_job_description_chars
    client = _api_client()

    response = client.post(
        "/rubrics/from-job-description",
        json={"name": "r", "text": "x" * (limit + 1)},
    )

    assert response.status_code == 413


def test_the_app_refuses_a_caller_who_will_not_stop():
    from veriquill.config import get_settings

    settings = get_settings()
    limit = get_settings().max_job_description_chars
    client = _api_client()
    oversized = {"name": "r", "text": "x" * (limit + 1)}

    for _ in range(settings.api_rate_limit):
        assert client.post("/rubrics/from-job-description", json=oversized).status_code == 413

    assert client.post("/rubrics/from-job-description", json=oversized).status_code == 429


def test_the_app_refuses_an_oversized_request_body_outright():
    from veriquill.config import get_settings

    client = _api_client()
    over = b"x" * (get_settings().api_max_request_bytes + 1)

    response = client.post("/analyse", content=over, headers={"content-type": "application/json"})

    assert response.status_code == 413


def test_the_same_cap_is_enforced_under_the_api_prefix():
    """Both mountings are the same router, so a cap on one has to hold on both."""
    from veriquill.config import get_settings

    limit = get_settings().max_job_description_chars
    client = _api_client()

    response = client.post(
        "/api/rubrics/from-job-description",
        json={"name": "r", "text": "x" * (limit + 1)},
    )

    assert response.status_code == 413


# --- the analysis budget is shared across workers ---------------------------


def _shared(tmp_path, limit=2, window=60):
    """A limiter over its own database, as two workers would share one."""
    from contextlib import contextmanager

    from veriquill.api.limits import SharedWindowLimiter
    from veriquill.db import init_db, make_engine, make_session_factory

    engine = make_engine(tmp_path / "v.sqlite")
    init_db(engine)
    sessions = make_session_factory(engine)

    @contextmanager
    def factory():
        with sessions() as session:
            yield session
            session.commit()

    return SharedWindowLimiter(
        bucket="analysis", limit=limit, window_seconds=window, session_factory=factory
    ), factory


def test_a_caller_within_the_shared_budget_is_allowed(tmp_path):
    limiter, _ = _shared(tmp_path, limit=3)

    for _ in range(3):
        limiter.check("1.2.3.4", now=1000.0)


def test_a_caller_over_the_shared_budget_is_refused(tmp_path):
    limiter, _ = _shared(tmp_path, limit=2)
    limiter.check("1.2.3.4", now=1000.0)
    limiter.check("1.2.3.4", now=1000.0)

    with pytest.raises(LimitExceeded) as exc:
        limiter.check("1.2.3.4", now=1000.0)

    assert exc.value.status_code == 429


def test_two_workers_share_one_budget(tmp_path):
    """The whole point. In-process limiters gave a caller one budget each."""
    from contextlib import contextmanager

    from veriquill.api.limits import SharedWindowLimiter
    from veriquill.db import init_db, make_engine, make_session_factory

    engine = make_engine(tmp_path / "v.sqlite")
    init_db(engine)
    sessions = make_session_factory(engine)

    @contextmanager
    def factory():
        with sessions() as session:
            yield session
            session.commit()

    def worker():
        return SharedWindowLimiter(
            bucket="analysis", limit=2, window_seconds=60, session_factory=factory
        )

    worker().check("1.2.3.4", now=1000.0)
    worker().check("1.2.3.4", now=1000.0)

    with pytest.raises(LimitExceeded):
        worker().check("1.2.3.4", now=1000.0)


def test_the_shared_budget_refills_once_the_window_passes(tmp_path):
    limiter, _ = _shared(tmp_path, limit=1, window=60)
    limiter.check("1.2.3.4", now=1000.0)  # window 960

    with pytest.raises(LimitExceeded):
        limiter.check("1.2.3.4", now=1010.0)  # same window

    limiter.check("1.2.3.4", now=1090.0)  # window 1080


def test_a_fixed_window_lets_a_burst_cross_its_boundary(tmp_path):
    """Stated rather than discovered.

    A fixed window resets on the hour rather than sliding, so a caller can
    spend a full budget at the end of one and another at the start of the
    next. That is the standard cost of counting in one row instead of
    storing every request, and it bounds a caller at twice the budget rather
    than at the number of workers, which is what this replaced.
    """
    limiter, _ = _shared(tmp_path, limit=2, window=60)

    limiter.check("1.2.3.4", now=1019.0)
    limiter.check("1.2.3.4", now=1019.5)
    limiter.check("1.2.3.4", now=1021.0)
    limiter.check("1.2.3.4", now=1021.5)

    with pytest.raises(LimitExceeded):
        limiter.check("1.2.3.4", now=1022.0)


def test_one_caller_cannot_spend_anothers_shared_budget(tmp_path):
    limiter, _ = _shared(tmp_path, limit=1)
    limiter.check("1.2.3.4", now=1000.0)

    limiter.check("5.6.7.8", now=1000.0)


def test_a_zero_shared_limit_disables_it(tmp_path):
    limiter, _ = _shared(tmp_path, limit=0)

    for _ in range(50):
        limiter.check("1.2.3.4", now=1000.0)


def test_old_windows_do_not_accumulate(tmp_path):
    """A row per active caller, not a row per request ever made."""
    from veriquill.models import RateWindow

    limiter, factory = _shared(tmp_path, limit=100, window=60)

    for minute in range(20):
        limiter.check("1.2.3.4", now=1000.0 + minute * 60)

    with factory() as session:
        assert session.query(RateWindow).count() == 1

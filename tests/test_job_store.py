"""Intake jobs that outlive the process that started them.

A job the server forgets is not a neutral loss. The browser polls a job id, and
a process that forgot the id answers 404 - which reads as "this candidate was
never submitted" rather than "this analysis was interrupted". A tool whose whole
argument is that claims and evidence stay straight does not get to blur those.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.intake import IntakeError
from veriquill.store import SqlJobStore


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(tmp_path / "veriquill.sqlite")
    init_db(engine)
    sessions = make_session_factory(engine)

    @contextmanager
    def session_factory():
        with sessions() as session:
            yield session
            session.commit()

    return session_factory


@pytest.fixture
def store(factory) -> SqlJobStore:
    return SqlJobStore(factory)


def test_a_job_can_be_read_back_after_it_is_created(store):
    job = store.create("octocat")

    assert store.get(job.id).handle == "octocat"
    assert store.get(job.id).status == "queued"


def test_a_job_survives_a_new_store_over_the_same_database(factory):
    job = SqlJobStore(factory).create("octocat")

    restarted = SqlJobStore(factory)

    assert restarted.get(job.id).handle == "octocat"


def test_an_unknown_job_is_refused_not_invented(store):
    with pytest.raises(IntakeError, match="no intake job"):
        store.get("deadbeef")


def test_a_bad_handle_is_refused_the_same_way_the_memory_store_refuses_it(store):
    with pytest.raises(IntakeError):
        store.create("not a handle")
    with pytest.raises(IntakeError):
        store.create("   ")


def test_a_job_moves_through_its_states(store):
    job = store.create("octocat")

    assert store.start(job.id).status == "running"

    finished = store.finish(job.id, dossier_id=7)
    assert finished.status == "done"
    assert finished.dossier_id == 7
    assert finished.finished_at is not None


def test_a_failed_job_keeps_the_reason(store):
    job = store.create("octocat")

    failed = store.fail(job.id, "MissingTokenError: no GitHub token")

    assert failed.status == "failed"
    assert "MissingTokenError" in (failed.error or "")


def test_jobs_are_listed_newest_first(store):
    first = store.create("alice")
    second = store.create("bob")

    listed = [job.id for job in store.list()]

    assert listed.index(second.id) < listed.index(first.id)


def test_an_interrupted_job_is_failed_rather_than_left_running(factory):
    """The reason to persist at all: a crash must not leave a job polling forever."""
    store = SqlJobStore(factory)
    queued = store.create("alice")
    running = store.create("bob")
    store.start(running.id)
    done = store.create("carol")
    store.finish(done.id, dossier_id=1)

    restarted = SqlJobStore(factory)
    abandoned = restarted.abandon_unfinished("the server restarted mid-analysis")

    assert abandoned == 2
    assert restarted.get(queued.id).status == "failed"
    assert restarted.get(running.id).status == "failed"
    assert "restarted" in (restarted.get(running.id).error or "")
    assert restarted.get(done.id).status == "done"


def test_abandoning_twice_does_not_touch_a_job_that_already_failed(factory):
    store = SqlJobStore(factory)
    job = store.create("alice")
    store.start(job.id)
    store.abandon_unfinished("first restart")

    assert store.abandon_unfinished("second restart") == 0
    assert "first restart" in (store.get(job.id).error or "")


def test_a_stored_job_reports_a_timezone_aware_time(store):
    """SQLite drops the offset; a naive timestamp would serialise as local time."""
    job = store.create("octocat")

    assert store.get(job.id).created_at.tzinfo is not None


def test_the_job_a_store_returns_hides_no_filesystem_paths(store):
    job = store.create("octocat")

    assert set(store.get(job.id).to_dict()) == {
        "id",
        "handle",
        "status",
        "error",
        "dossier_id",
        "created_at",
        "finished_at",
    }

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


def test_a_second_process_reads_the_truth_rather_than_its_own_stale_copy(factory):
    """The correctness boundary of the read cache.

    A store only caches jobs it wrote itself, because only the writer can know
    the entry is current. A store that did not write the job must go to SQLite
    every time, or it would serve a status that moved on without it.
    """
    writer = SqlJobStore(factory)
    reader = SqlJobStore(factory)

    job = writer.create("octocat")

    # The reader has never written this job, so it must not be holding one.
    assert reader.get(job.id).status == "queued"

    writer.start(job.id)
    writer.finish(job.id, dossier_id=3)

    assert reader.get(job.id).status == "done"
    assert reader.get(job.id).dossier_id == 3


def test_reading_a_job_never_populates_the_cache(factory):
    """Caching on read is exactly the bug the write-through rule avoids."""
    reader = SqlJobStore(factory)
    job = SqlJobStore(factory).create("octocat")

    reader.get(job.id)

    assert job.id not in reader._own


def test_the_writer_sees_its_own_updates_immediately(factory):
    store = SqlJobStore(factory)
    job = store.create("octocat")

    store.start(job.id)
    assert store.get(job.id).status == "running"

    store.fail(job.id, "clone timed out")
    assert store.get(job.id).status == "failed"
    assert store.get(job.id).error == "clone timed out"


def test_abandoning_drops_cached_copies_rather_than_serving_them(factory):
    """A cached "running" would outlive the row that says it was abandoned."""
    store = SqlJobStore(factory)
    job = store.create("octocat")
    store.start(job.id)

    store.abandon_unfinished("the server restarted mid-analysis")

    assert store.get(job.id).status == "failed"
    assert "restarted" in (store.get(job.id).error or "")


def test_the_cache_is_bounded_and_evicting_costs_only_a_disk_read(factory):
    """The cache is an optimisation correctness never depends on."""
    store = SqlJobStore(factory)
    store.CACHE_LIMIT = 4

    jobs = [store.create(f"cand{i}") for i in range(10)]

    assert len(store._own) == 4
    # Evicted jobs are still readable; they just come from SQLite now.
    assert store.get(jobs[0].id).handle == "cand0"
    assert store.get(jobs[-1].id).handle == "cand9"


def test_an_evicted_job_still_reports_its_updates(factory):
    store = SqlJobStore(factory)
    store.CACHE_LIMIT = 2

    job = store.create("alice")
    for i in range(5):
        store.create(f"filler{i}")

    assert job.id not in store._own
    store.finish(job.id, dossier_id=11)

    assert store.get(job.id).status == "done"
    assert store.get(job.id).dossier_id == 11


def test_a_run_summary_is_stored_and_read_back(factory):
    from veriquill.store import load_run, save_run

    with factory() as session:
        save_run(session, "abc123", "octocat", {"handle": "octocat", "repositories": []})
    with factory() as session:
        assert load_run(session, "abc123")["handle"] == "octocat"


def test_an_unknown_run_is_refused_not_invented(factory):
    from veriquill.store import StoreError, load_run

    with factory() as session, pytest.raises(StoreError, match="not found"):
        load_run(session, "nope")


def test_old_run_summaries_are_pruned(factory, monkeypatch):
    """They are large working state, and the dossier is what a decision rests on."""
    from veriquill import store

    monkeypatch.setattr(store, "RUN_RETENTION", 3)

    for index in range(6):
        with factory() as session:
            store.save_run(session, f"run{index}", "octocat", {"n": index})

    with factory() as session:
        kept = session.scalars(
            store.select(store.RunSummaryRecord.id)
        ).all()

    assert len(kept) == 3
    # The newest survive; the oldest are the ones dropped.
    assert "run5" in kept
    assert "run0" not in kept

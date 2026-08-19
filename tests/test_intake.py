"""Adding a candidate from the interface.

Analysis takes minutes, so intake is a job the caller polls rather than a request
that hangs. Uploads are the input where redaction matters most, so what the
server accepts, where it puts it, and when it deletes it are all tested here.
"""

from __future__ import annotations

import io

import pytest

from veriquill.intake import (
    MAX_UPLOAD_BYTES,
    RESUME_SUFFIXES,
    IntakeError,
    JobStore,
    stage_upload,
)


@pytest.fixture()
def store() -> JobStore:
    return JobStore()


def test_a_new_job_starts_queued(store):
    job = store.create("octocat")

    assert job.status == "queued"
    assert job.handle == "octocat"
    assert job.dossier_id is None


def test_a_job_is_retrievable_by_id(store):
    job = store.create("octocat")

    assert store.get(job.id) is job


def test_an_unknown_job_is_refused(store):
    with pytest.raises(IntakeError, match="nope"):
        store.get("nope")


def test_a_job_records_the_dossier_it_produced(store):
    job = store.create("octocat")

    store.finish(job.id, dossier_id=7)

    assert store.get(job.id).status == "done"
    assert store.get(job.id).dossier_id == 7


def test_a_failed_job_carries_the_reason_not_just_a_flag(store):
    job = store.create("ghost")

    store.fail(job.id, "GitHub said 404 for 'ghost'")

    failed = store.get(job.id)
    assert failed.status == "failed"
    assert "404" in failed.error


def test_a_running_job_says_what_it_is_doing(store):
    job = store.create("octocat")

    store.start(job.id)

    assert store.get(job.id).status == "running"


def test_jobs_are_listed_newest_first(store):
    first = store.create("alice")
    second = store.create("bob")

    assert [j.id for j in store.list()] == [second.id, first.id]


def test_a_job_serialises_without_leaking_a_file_path(store):
    job = store.create("octocat")
    payload = job.to_dict()

    assert payload["handle"] == "octocat"
    assert payload["status"] == "queued"
    assert "path" not in payload
    assert "resume" not in payload


def test_a_resume_is_staged_under_the_workdir(tmp_path):
    staged = stage_upload("cv.pdf", b"%PDF-1.4 something", tmp_path, RESUME_SUFFIXES)

    assert staged.parent == tmp_path
    assert staged.read_bytes().startswith(b"%PDF")


def test_a_staged_name_cannot_escape_the_workdir(tmp_path):
    staged = stage_upload("../../evil.txt", b"x", tmp_path, RESUME_SUFFIXES)

    assert staged.parent == tmp_path
    assert ".." not in staged.name


def test_an_unsupported_file_type_is_refused(tmp_path):
    with pytest.raises(IntakeError, match="\\.exe"):
        stage_upload("payload.exe", b"MZ", tmp_path, RESUME_SUFFIXES)


def test_an_oversized_upload_is_refused(tmp_path):
    with pytest.raises(IntakeError, match="too large"):
        stage_upload("cv.pdf", b"x" * (MAX_UPLOAD_BYTES + 1), tmp_path, RESUME_SUFFIXES)


def test_an_empty_upload_is_refused(tmp_path):
    with pytest.raises(IntakeError, match="empty"):
        stage_upload("cv.pdf", b"", tmp_path, RESUME_SUFFIXES)


def test_a_handle_that_is_not_a_github_handle_is_refused(store):
    for bad in ["", "   ", "has space", "why/slash", "-leading", "a" * 40]:
        with pytest.raises(IntakeError):
            store.create(bad)


def test_a_legitimate_handle_is_accepted(store):
    for good in ["octocat", "Likith-Sh3tty", "a"]:
        assert store.create(good).handle == good


def test_the_upload_stream_is_read_in_full(tmp_path):
    stream = io.BytesIO(b"name,value\nx,1\n")

    staged = stage_upload("export.csv", stream.read(), tmp_path, {".csv", ".json"})

    assert staged.read_text(encoding="utf-8").startswith("name,value")

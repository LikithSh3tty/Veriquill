"""HTTP surface.

This layer holds no analysis logic. It starts runs, ranks stored dossiers, and
carries review actions through to the gate. Every refusal the review layer makes
is surfaced as a status code rather than smoothed over: a pending comparison
returns 409, because "not yet reviewed" is a real state and not an error to hide.

There is no authentication here. `actor` is whatever the caller supplies, and a
real deployment has to put an authenticated identity in that field.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from veriquill import __version__
from veriquill.config import get_settings
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.intake import (
    LINKEDIN_SUFFIXES,
    RESUME_SUFFIXES,
    IntakeError,
    JobStore,
    stage_upload,
)
from veriquill.pipeline import analyse_candidate, build_candidate_dossier
from veriquill.review import ReviewError, audit_log, effective_result, export_payload, record_action
from veriquill.review import approve as approve_comparison
from veriquill.rubric import Rubric, RubricError
from veriquill.store import (
    StoreError,
    create_comparison,
    get_comparison,
    list_candidates,
    list_rubrics,
    save_dossier,
    save_rubric,
)

app = FastAPI(title="Veriquill", version=__version__)

# Analysis runs stay in-process: they are large, transient, and superseded by the
# dossier the moment one is built. Everything a reviewer acts on lives in SQLite.
_RUNS: dict[str, dict[str, Any]] = {}

# Intake jobs are transient; the dossier each one writes is what persists.
_JOBS = JobStore()


@contextmanager
def _session() -> Iterator[Session]:
    settings = get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
        session.commit()


class AnalyseRequest(BaseModel):
    handle: str


class ComparisonRequest(BaseModel):
    rubric: str
    candidates: list[str]


class ReviewRequest(BaseModel):
    actor: str
    action: str
    candidate: str
    reason: str
    target: str | None = None


class ApprovalRequest(BaseModel):
    actor: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/analyse")
async def start_analysis(request: AnalyseRequest) -> dict[str, str]:
    run_id = uuid4().hex
    settings = get_settings()
    summary = await analyse_candidate(request.handle, settings)
    _RUNS[run_id] = summary.to_dict()
    return {"run_id": run_id, "status": "complete"}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    summary = _RUNS.get(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "summary": summary}


@app.post("/rubrics")
def create_rubric(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        rubric = Rubric.from_dict(payload)
    except RubricError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with _session() as session:
        save_rubric(session, rubric)
    return {"rubric": rubric.to_dict()}


@app.get("/rubrics")
def read_rubrics() -> dict[str, Any]:
    with _session() as session:
        return {"rubrics": [rubric.to_dict() for rubric in list_rubrics(session)]}


@app.post("/comparisons")
def create_comparison_endpoint(request: ComparisonRequest) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = create_comparison(session, request.rubric, request.candidates)
            result = effective_result(session, comparison)
        except StoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "result": result}


@app.get("/comparisons/{comparison_id}")
def read_comparison(comparison_id: int) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "comparison_id": comparison.id,
            "result": effective_result(session, comparison),
        }


@app.post("/comparisons/{comparison_id}/review")
def review_comparison(comparison_id: int, request: ReviewRequest) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            record_action(
                session,
                comparison,
                actor=request.actor,
                action=request.action,
                candidate=request.candidate,
                target=request.target,
                reason=request.reason,
            )
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "status": comparison.status}


@app.post("/comparisons/{comparison_id}/approve")
def approve_endpoint(comparison_id: int, request: ApprovalRequest) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            approve_comparison(session, comparison, request.actor)
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "status": comparison.status}


@app.get("/comparisons/{comparison_id}/export")
def export_endpoint(comparison_id: int) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return export_payload(session, comparison)
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/comparisons/{comparison_id}/dossiers")
def read_dossiers(comparison_id: int) -> dict[str, Any]:
    """The dossiers behind a comparison, keyed by candidate.

    The review screen acts on individual flags by id, so it has to be able to
    read the register those ids come from. The ranked result deliberately
    carries scores rather than findings, so this is a separate call.
    """
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "comparison_id": comparison.id,
            "dossiers": {
                entry.candidate_handle: entry.dossier.payload
                for entry in sorted(comparison.entries, key=lambda e: e.id)
            },
        }


@app.get("/comparisons/{comparison_id}/audit")
def audit_endpoint(comparison_id: int) -> dict[str, Any]:
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "comparison_id": comparison.id,
            "audit_log": audit_log(session, comparison),
        }


async def _run_intake(job_id: str, handle: str, resume: Path | None, linkedin: Path | None) -> None:
    """Analyse a candidate and store the dossier, then clean up the uploads.

    Any failure is recorded against the job with its reason. A candidate who
    cannot be analysed is never a silent no-op, and never a crashed server.
    """
    settings = get_settings()
    _JOBS.start(job_id)
    try:
        report = await build_candidate_dossier(handle, settings, resume=resume, linkedin=linkedin)
        with _session() as session:
            record = save_dossier(session, report)
            dossier_id = record.id
        _JOBS.finish(job_id, dossier_id=dossier_id)
    except Exception as exc:
        _JOBS.fail(job_id, f"{type(exc).__name__}: {exc}")
    finally:
        # Uploaded documents are working material, not records. The claims they
        # produced are stored; the files themselves are not kept.
        for path in (resume, linkedin):
            if path is not None:
                shutil.rmtree(path.parent, ignore_errors=True)


@app.post("/candidates", status_code=202)
async def add_candidate(
    background: BackgroundTasks,
    handle: str = Form(...),
    resume: UploadFile | None = File(None),
    linkedin: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Start analysing a candidate. Returns immediately with a job to poll.

    Cloning a portfolio takes minutes, so this cannot be a request that waits.
    """
    settings = get_settings()
    settings.ensure_dirs()

    try:
        job = _JOBS.create(handle)
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    staging = Path(tempfile.mkdtemp(prefix="veriquill-intake-", dir=settings.workdir))
    try:
        resume_path = (
            stage_upload(resume.filename or "", await resume.read(), staging, RESUME_SUFFIXES)
            if resume is not None and resume.filename
            else None
        )
        linkedin_path = (
            stage_upload(
                linkedin.filename or "", await linkedin.read(), staging, LINKEDIN_SUFFIXES
            )
            if linkedin is not None and linkedin.filename
            else None
        )
    except IntakeError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _JOBS.fail(job.id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background.add_task(_run_intake, job.id, job.handle, resume_path, linkedin_path)
    return {"job": job.to_dict()}


@app.get("/candidates/jobs/{job_id}")
def read_intake_job(job_id: str) -> dict[str, Any]:
    try:
        return {"job": _JOBS.get(job_id).to_dict()}
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/candidates/jobs")
def read_intake_jobs() -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in _JOBS.list()]}


@app.get("/candidates")
def read_candidates() -> dict[str, Any]:
    """Everyone with a stored dossier, and so everyone who can be ranked."""
    with _session() as session:
        return {"candidates": list_candidates(session)}

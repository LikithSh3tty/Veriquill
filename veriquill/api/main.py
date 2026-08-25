"""HTTP surface.

This layer holds no analysis logic. It starts runs, ranks stored dossiers, and
carries review actions through to the gate. Every refusal the review layer makes
is surfaced as a status code rather than smoothed over: a pending comparison
returns 409, because "not yet reviewed" is a real state and not an error to hide.

Authentication is opt in and off until keys are configured. Where they are, the
actor written into the audit log comes from the caller's key rather than from the
request body, because an append-only log of unverified names is not an audit
trail. See `veriquill.api.auth`.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from veriquill import __version__
from veriquill.api.auth import (
    ANONYMOUS,
    PUBLIC_PATHS,
    Identity,
    actor_for,
    resolve,
    warn_if_open,
)
from veriquill.api.interface import mount_interface
from veriquill.api.limits import (
    BodySizeLimitMiddleware,
    FixedWindowLimiter,
    LimitExceeded,
    enforce,
    read_capped,
)
from veriquill.config import get_settings
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.intake import (
    LINKEDIN_SUFFIXES,
    MAX_UPLOAD_BYTES,
    RESUME_SUFFIXES,
    IntakeError,
    stage_upload,
)
from veriquill.jobspec import derive_rubric, read_job_description
from veriquill.pipeline import (
    account_refs_fingerprint,
    analyse_candidate,
    build_candidate_dossier,
)
from veriquill.review import ReviewError, audit_log, effective_result, export_payload, record_action
from veriquill.review import approve as approve_comparison
from veriquill.rubric import Rubric, RubricError
from veriquill.store import (
    SqlJobStore,
    StoreError,
    create_comparison,
    get_comparison,
    list_candidates,
    list_rubrics,
    load_run,
    reusable_dossier,
    save_dossier,
    save_rubric,
    save_run,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Close out whatever the last process left open.

    Persisting jobs without this would be worse than not persisting them: a job
    left "running" by a restart would poll as running forever, and the interface
    would show work in progress that nothing is doing. Say it was interrupted so
    the recruiter resubmits.
    """
    warn_if_open()
    _JOBS.abandon_unfinished(
        "the server restarted while this analysis was running; submit the candidate again"
    )
    yield


app = FastAPI(title="Veriquill", version=__version__, lifespan=_lifespan)

_limit_settings = get_settings()
app.add_middleware(
    BodySizeLimitMiddleware, max_bytes=_limit_settings.api_max_request_bytes
)

# Two budgets, because two costs. Reading a stored comparison is cheap and a
# reviewer clicking through a cohort should never hit a wall; starting an
# analysis clones a portfolio and walks its history, so a handful per minute is
# already generous for a tool one human drives.
_reads = FixedWindowLimiter(
    limit=_limit_settings.api_rate_limit,
    window_seconds=_limit_settings.api_rate_limit_window_seconds,
)
_analyses = FixedWindowLimiter(
    limit=_limit_settings.api_analysis_rate_limit,
    window_seconds=_limit_settings.api_rate_limit_window_seconds,
)

def _authenticate(request: Request) -> Identity:
    """Resolve the caller once per request, and hang it on the request.

    A router-level dependency rather than middleware, so it covers every API
    route under both mountings and leaves the static interface alone: the
    dashboard has to load before it can ask anyone for a key.
    """
    identity = ANONYMOUS if request.url.path in PUBLIC_PATHS else resolve(request)
    request.state.identity = identity
    return identity


def _identity(request: Request) -> Identity:
    return getattr(request.state, "identity", ANONYMOUS)


# Every route is defined once and served twice: at the root, where the CLI and
# the docs address it, and under /api, where the browser bundle addresses it so
# a single origin can serve the interface and the API it talks to.
router = APIRouter(dependencies=[Depends(_authenticate)])

# Run summaries are persisted for the same reason intake jobs are. The old
# argument for keeping them in a dict was that a run is large, transient, and
# superseded by the dossier the moment one is built. The first two hold; the
# third does not yet, because the caller is handed a run id and has to fetch the
# summary separately. A restart in between turned a completed analysis into a
# 404, which reads as "this never ran" rather than "this was lost".

# Intake jobs are persisted. They are working state rather than evidence, but a
# job the process forgets answers 404 to a browser that is polling it, and a 404
# reads as "this candidate was never submitted" rather than "this analysis was
# interrupted". Those are different facts.
_JOBS = SqlJobStore(lambda: _session())


@lru_cache(maxsize=8)
def _prepared_session_factory(db_path: Path, _data_dir: Path) -> sessionmaker[Session]:
    """Build the engine once per database, not once per request.

    This used to run inside `_session`, so every request constructed a new
    engine and ran `create_all` before it could ask its question - eleven times
    the cost of the query itself. That was tolerable while only comparatively
    rare endpoints paid it; it stopped being tolerable when job polling, which
    the interface repeats every 1.5 seconds, started going through here too.

    Creating the working directories belongs here for the same reason: it is
    two `mkdir` calls that only have to succeed once, and doing them per request
    put filesystem syscalls on the path of every poll.

    Keyed on both paths, so a test pointing at a fresh data directory gets a
    fresh engine and its own directories rather than the last one's.
    """
    get_settings().ensure_dirs()
    engine = make_engine(db_path)
    init_db(engine)
    return make_session_factory(engine)


@contextmanager
def _session() -> Iterator[Session]:
    settings = get_settings()
    factory = _prepared_session_factory(settings.db_path, settings.data_dir)
    with factory() as session:
        yield session
        session.commit()


class AnalyseRequest(BaseModel):
    handle: str


class ComparisonRequest(BaseModel):
    rubric: str
    candidates: list[str]


class ReviewRequest(BaseModel):
    # Optional, because an authenticated caller's identity comes from their key.
    # Supplying a different one is refused rather than ignored: the request meant
    # something by it, and silently overwriting it would leave the caller
    # believing they had recorded something they had not.
    actor: str = ""
    action: str
    candidate: str
    reason: str
    target: str | None = None


class ApprovalRequest(BaseModel):
    actor: str = ""


class JobDescriptionRequest(BaseModel):
    name: str
    text: str


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.post("/analyse")
async def start_analysis(request: AnalyseRequest, http_request: Request) -> dict[str, str]:
    enforce(_analyses, http_request)
    run_id = uuid4().hex
    settings = get_settings()
    summary = await analyse_candidate(request.handle, settings)
    with _session() as session:
        save_run(session, run_id, request.handle, summary.to_dict())
    return {"run_id": run_id, "status": "complete"}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with _session() as session:
        try:
            summary = load_run(session, run_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": run_id, "summary": summary}


@router.post("/rubrics")
def create_rubric(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        rubric = Rubric.from_dict(payload)
    except RubricError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with _session() as session:
        save_rubric(session, rubric)
    return {"rubric": rubric.to_dict()}


@router.get("/rubrics")
def read_rubrics() -> dict[str, Any]:
    with _session() as session:
        return {"rubrics": [rubric.to_dict() for rubric in list_rubrics(session)]}


@router.post("/comparisons")
def create_comparison_endpoint(
    request: ComparisonRequest, http_request: Request
) -> dict[str, Any]:
    enforce(_reads, http_request)
    with _session() as session:
        try:
            comparison = create_comparison(session, request.rubric, request.candidates)
            result = effective_result(session, comparison)
        except StoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "result": result}


@router.get("/comparisons/{comparison_id}")
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


@router.post("/comparisons/{comparison_id}/review")
def review_comparison(
    comparison_id: int, request: ReviewRequest, http_request: Request
) -> dict[str, Any]:
    actor = actor_for(_identity(http_request), request.actor)
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            record_action(
                session,
                comparison,
                actor=actor,
                action=request.action,
                candidate=request.candidate,
                target=request.target,
                reason=request.reason,
            )
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "status": comparison.status}


@router.post("/comparisons/{comparison_id}/approve")
def approve_endpoint(
    comparison_id: int, request: ApprovalRequest, http_request: Request
) -> dict[str, Any]:
    actor = actor_for(_identity(http_request), request.actor)
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            approve_comparison(session, comparison, actor)
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"comparison_id": comparison.id, "status": comparison.status}


@router.get("/comparisons/{comparison_id}/export")
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


@router.get("/comparisons/{comparison_id}/dossiers")
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


@router.get("/comparisons/{comparison_id}/audit")
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


async def _run_intake(
    job_id: str,
    handle: str,
    resume: Path | None,
    linkedin: Path | None,
    job_description: str = "",
) -> None:
    """Analyse a candidate and store the dossier, then clean up the uploads.

    Any failure is recorded against the job with its reason. A candidate who
    cannot be analysed is never a silent no-op, and never a crashed server.
    """
    settings = get_settings()
    _JOBS.start(job_id)
    try:
        # Ask what the repositories currently hold before cloning any of
        # them. A stored dossier stamped with the same fingerprint was built
        # from the same histories by the same code, so rebuilding it would
        # spend minutes to reach the identical artifact. Documents are the
        # exception: new ones mean new claims to reconcile.
        reused: dict[str, Any] | None = None
        if resume is None and linkedin is None:
            fingerprint = await account_refs_fingerprint(
                handle, settings, job_description=job_description
            )
            with _session() as session:
                reused = reusable_dossier(session, handle, fingerprint)

        report = reused or await build_candidate_dossier(
            handle,
            settings,
            resume=resume,
            linkedin=linkedin,
            job_description=job_description,
        )
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


@router.post("/candidates", status_code=202)
async def add_candidate(
    background: BackgroundTasks,
    http_request: Request,
    handle: str = Form(...),
    job_description: str = Form(""),
    resume: UploadFile | None = File(None),
    linkedin: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Start analysing a candidate. Returns immediately with a job to poll.

    Cloning a portfolio takes minutes, so this cannot be a request that waits.
    """
    enforce(_analyses, http_request)
    settings = get_settings()
    settings.ensure_dirs()

    if len(job_description) > settings.max_job_description_chars:
        raise HTTPException(
            status_code=413,
            detail=(
                "the job description is longer than the "
                f"{settings.max_job_description_chars} character limit"
            ),
        )

    try:
        job = _JOBS.create(handle)
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    staging = Path(tempfile.mkdtemp(prefix="veriquill-intake-", dir=settings.workdir))
    try:
        # Read bounded. `UploadFile.read()` buffers the whole body before
        # anything checks its size, which makes stage_upload's cap useless as a
        # defence: the memory is spent by the time the limit is consulted.
        resume_path = (
            stage_upload(
                resume.filename or "",
                await read_capped(resume, MAX_UPLOAD_BYTES, "the resume"),
                staging,
                RESUME_SUFFIXES,
            )
            if resume is not None and resume.filename
            else None
        )
        linkedin_path = (
            stage_upload(
                linkedin.filename or "",
                await read_capped(linkedin, MAX_UPLOAD_BYTES, "the LinkedIn export"),
                staging,
                LINKEDIN_SUFFIXES,
            )
            if linkedin is not None and linkedin.filename
            else None
        )
    except LimitExceeded as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _JOBS.fail(job.id, exc.detail)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except IntakeError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        _JOBS.fail(job.id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background.add_task(
        _run_intake, job.id, job.handle, resume_path, linkedin_path, job_description
    )
    return {"job": job.to_dict()}


@router.post("/rubrics/from-job-description")
def rubric_from_job_description(
    request: JobDescriptionRequest, http_request: Request
) -> dict[str, Any]:
    """Derive a rubric from a posting, and say which phrases raised what.

    The derivation is returned alongside the rubric so a recruiter can check the
    reasoning before ranking anyone against it, and so a candidate can be told
    why a dimension counted for what it did.
    """
    enforce(_reads, http_request)

    limit = get_settings().max_job_description_chars
    if len(request.text) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"the job description is longer than the {limit} character limit",
        )

    try:
        rubric = derive_rubric(request.name, request.text)
    except (ValueError, RubricError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with _session() as session:
        save_rubric(session, rubric)

    return {
        "rubric": rubric.to_dict(),
        "derivation": read_job_description(request.text).to_dict(),
    }


@router.get("/candidates/jobs/{job_id}")
def read_intake_job(job_id: str) -> dict[str, Any]:
    try:
        return {"job": _JOBS.get(job_id).to_dict()}
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/candidates/jobs")
def read_intake_jobs() -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in _JOBS.list()]}


@router.get("/candidates")
def read_candidates() -> dict[str, Any]:
    """Everyone with a stored dossier, and so everyone who can be ranked."""
    with _session() as session:
        return {"candidates": list_candidates(session)}


app.include_router(router)
# The second copy stays out of the schema: it is the same surface, and listing it
# twice would leave a reader guessing which one is authoritative.
app.include_router(router, prefix="/api", include_in_schema=False)

# Last, so it catches only what the API did not: a checkout with no build serves
# the API alone, and the pages 404 rather than the process refusing to start.
mount_interface(app, get_settings().ui_dist)

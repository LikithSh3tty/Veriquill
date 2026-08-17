"""HTTP surface.

This layer holds no analysis logic. It starts runs, ranks stored dossiers, and
carries review actions through to the gate. Every refusal the review layer makes
is surfaced as a status code rather than smoothed over: a pending comparison
returns 409, because "not yet reviewed" is a real state and not an error to hide.

There is no authentication here. `actor` is whatever the caller supplies, and a
real deployment has to put an authenticated identity in that field.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from veriquill import __version__
from veriquill.config import get_settings
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.pipeline import analyse_candidate
from veriquill.review import ReviewError, audit_log, effective_result, export_payload, record_action
from veriquill.review import approve as approve_comparison
from veriquill.rubric import Rubric, RubricError
from veriquill.store import (
    StoreError,
    create_comparison,
    get_comparison,
    list_rubrics,
    save_rubric,
)

app = FastAPI(title="Veriquill", version=__version__)

# Analysis runs stay in-process: they are large, transient, and superseded by the
# dossier the moment one is built. Everything a reviewer acts on lives in SQLite.
_RUNS: dict[str, dict[str, Any]] = {}


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

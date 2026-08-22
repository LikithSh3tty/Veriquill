"""Reading and writing the things a review gate needs to outlive a process.

Dossiers and machine scores are written once. Nothing here offers a way to edit
them, because a reviewer disagreeing with Veriquill must not be able to make it
look as though Veriquill never said it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veriquill.intake import IntakeError, Job, validate_handle
from veriquill.models import (
    ComparisonEntry,
    ComparisonRecord,
    DossierRecord,
    IntakeJobRecord,
    RubricRecord,
)
from veriquill.rank.score import score_candidate
from veriquill.rubric import Rubric


class StoreError(ValueError):
    """Raised when the store is asked for something that is not there."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_rubric(session: Session, rubric: Rubric) -> RubricRecord:
    record = RubricRecord(
        name=rubric.name,
        version=rubric.version,
        weights=dict(rubric.weights),
        minimum_bars=dict(rubric.minimum_bars),
        created_at=_now(),
    )
    session.add(record)
    session.flush()
    return record


def _latest_rubric_record(session: Session, name: str) -> RubricRecord:
    record = session.scalars(
        select(RubricRecord).where(RubricRecord.name == name).order_by(RubricRecord.id.desc())
    ).first()
    if record is None:
        raise StoreError(f"no rubric named {name!r} has been stored")
    return record


def load_rubric(session: Session, name: str) -> Rubric:
    record = _latest_rubric_record(session, name)
    return Rubric(
        name=record.name,
        version=record.version,
        weights=dict(record.weights),
        minimum_bars=dict(record.minimum_bars),
    )


def list_rubrics(session: Session) -> list[Rubric]:
    names = sorted(set(session.scalars(select(RubricRecord.name)).all()))
    return [load_rubric(session, name) for name in names]


def save_dossier(session: Session, payload: dict[str, Any]) -> DossierRecord:
    handle = str(payload.get("handle") or "").strip()
    if not handle:
        raise StoreError("dossier has no handle; it cannot be stored against a candidate")

    record = DossierRecord(
        candidate_handle=handle,
        payload=payload,
        payload_hash=payload_hash(payload),
        created_at=_now(),
    )
    session.add(record)
    session.flush()
    return record


def latest_dossier(session: Session, handle: str) -> DossierRecord:
    record = session.scalars(
        select(DossierRecord)
        .where(DossierRecord.candidate_handle == handle)
        .order_by(DossierRecord.id.desc())
    ).first()
    if record is None:
        raise StoreError(f"no dossier stored for {handle!r}; analyse the candidate first")
    return record


def create_comparison(
    session: Session, rubric_name: str, handles: list[str]
) -> ComparisonRecord:
    if not handles:
        raise StoreError("a comparison needs at least one candidate")

    rubric_record = _latest_rubric_record(session, rubric_name)
    rubric = load_rubric(session, rubric_name)

    comparison = ComparisonRecord(
        rubric_id=rubric_record.id,
        status="pending_review",
        revision=0,
        created_at=_now(),
    )
    session.add(comparison)
    session.flush()

    scored: list[tuple[str, ComparisonEntry, float | None]] = []
    for handle in handles:
        dossier = latest_dossier(session, handle)
        result = score_candidate(dossier.payload, rubric)
        entry = ComparisonEntry(
            comparison_id=comparison.id,
            dossier_id=dossier.id,
            candidate_handle=handle,
            machine_score=result.to_dict(),
            machine_rank=None,
        )
        session.add(entry)
        scored.append((handle, entry, result.score))

    session.flush()

    ranked = sorted(
        (item for item in scored if item[2] is not None),
        key=lambda item: (-float(item[2]), item[0]),
    )
    for position, (_handle, entry, _score) in enumerate(ranked, start=1):
        entry.machine_rank = position

    session.flush()
    return comparison


def get_comparison(session: Session, comparison_id: int) -> ComparisonRecord:
    comparison = session.get(ComparisonRecord, comparison_id)
    if comparison is None:
        raise StoreError(f"comparison {comparison_id} not found")
    return comparison


def dossier_payloads(session: Session, comparison: ComparisonRecord) -> list[dict[str, Any]]:
    return [entry.dossier.payload for entry in sorted(comparison.entries, key=lambda e: e.id)]


def list_candidates(session: Session) -> list[dict[str, Any]]:
    """Every candidate with a stored dossier, newest first.

    The interface needs to know who can be ranked, which is exactly who has a
    dossier — not who was ever analysed.
    """
    records = session.scalars(
        select(DossierRecord).order_by(DossierRecord.id.desc())
    ).all()

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.candidate_handle in seen:
            continue
        seen.add(record.candidate_handle)
        payload = record.payload or {}
        rows.append(
            {
                "handle": record.candidate_handle,
                "dossier_id": record.id,
                "stored_at": record.created_at.isoformat(),
                "flags": len(payload.get("red_flag_register") or []),
            }
        )
    return rows


def _as_utc(moment: datetime | None) -> datetime | None:
    """SQLite drops the offset. Reattach UTC rather than hand back a naive time."""
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _to_job(record: IntakeJobRecord) -> Job:
    created = _as_utc(record.created_at)
    return Job(
        id=record.id,
        handle=record.handle,
        status=record.status,  # type: ignore[arg-type]
        error=record.error,
        dossier_id=record.dossier_id,
        created_at=created if created is not None else _now(),
        finished_at=_as_utc(record.finished_at),
    )


class SqlJobStore:
    """Intake jobs that outlive the process that started them.

    The in-memory store was fine until you asked what a restart actually costs.
    The browser polls a job id; a process that forgot the id answers 404, and a
    404 reads as "this candidate was never submitted" rather than "this analysis
    was interrupted". Those are different facts, and a tool that exists to keep
    claims and evidence straight does not get to blur them.

    Jobs are working state, not evidence. What a decision rests on is the
    dossier, which is written by the job and stored separately.

    Reads of a job this process wrote are served from memory, which is what
    makes the durability free at the point the interface actually pays for it:
    the browser polls one job id every 1.5 seconds, and that poll should not be
    a disk read.

    The cache is write-through and never populated by a read. That distinction
    is the whole correctness argument. A job is only ever written by the process
    that accepted it - the background task runs there - so that process's copy
    cannot go stale. Any other process has no entry, falls through to SQLite,
    and gets the truth. Caching on read is what would break this, by letting a
    process that is not the writer hold an answer it has no way to refresh.

    It is bounded, and eviction costs nothing but a disk read, because a miss
    falls through to the same query a cold process would run. That is the other
    half of the design: the cache is an optimisation the correctness never
    depends on, so it can be dropped, capped, or emptied at any point.
    """

    #: Jobs kept in memory. A recruiter works through a cohort, not a backlog of
    #: thousands, so this is far more than the polling ever reaches back to.
    CACHE_LIMIT = 256

    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]]) -> None:
        self._session_factory = session_factory
        self._own: dict[str, Job] = {}

    def _remember(self, job: Job) -> None:
        self._own[job.id] = job
        while len(self._own) > self.CACHE_LIMIT:
            self._own.pop(next(iter(self._own)))

    def create(self, handle: str) -> Job:
        handle = validate_handle(handle)
        job = Job(id=uuid.uuid4().hex, handle=handle)
        with self._session_factory() as session:
            session.add(
                IntakeJobRecord(
                    id=job.id,
                    handle=job.handle,
                    status=job.status,
                    created_at=job.created_at,
                )
            )
        self._remember(job)
        return job

    def get(self, job_id: str) -> Job:
        own = self._own.get(job_id)
        if own is not None:
            return own

        with self._session_factory() as session:
            record = session.get(IntakeJobRecord, job_id)
            if record is None:
                raise IntakeError(f"no intake job {job_id!r}")
            # Deliberately not cached. See the class docstring: an entry this
            # process did not write is one it has no way to know has changed.
            return _to_job(record)

    def list(self) -> list[Job]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IntakeJobRecord).order_by(IntakeJobRecord.created_at.desc())
            ).all()
            return [_to_job(record) for record in records]

    def _update(self, job_id: str, **changes: Any) -> Job:
        with self._session_factory() as session:
            record = session.get(IntakeJobRecord, job_id)
            if record is None:
                raise IntakeError(f"no intake job {job_id!r}")
            for attribute, value in changes.items():
                setattr(record, attribute, value)
            session.flush()
            job = _to_job(record)

        # Write-through: this process just became the authority on this job.
        if job_id in self._own:
            self._remember(job)
        return job

    def start(self, job_id: str) -> Job:
        return self._update(job_id, status="running")

    def finish(self, job_id: str, dossier_id: int) -> Job:
        return self._update(
            job_id, status="done", dossier_id=dossier_id, finished_at=_now()
        )

    def fail(self, job_id: str, error: str) -> Job:
        return self._update(job_id, status="failed", error=error, finished_at=_now())

    def abandon_unfinished(self, reason: str) -> int:
        """Fail every job that was still open when the process last stopped.

        Persistence without this would be worse than no persistence: a job left
        "running" by a crash would poll as running forever, and the interface
        would show work in progress that no process is doing. Say plainly that
        it was interrupted, so the recruiter resubmits instead of waiting.

        Call it at startup, before anything new is accepted.
        """
        with self._session_factory() as session:
            stale = session.scalars(
                select(IntakeJobRecord).where(
                    IntakeJobRecord.status.in_(("queued", "running"))
                )
            ).all()
            for record in stale:
                record.status = "failed"
                record.error = reason
                record.finished_at = _now()

            # This writes rows the cache may be holding older copies of, so the
            # cache is dropped rather than patched. It is startup: there is
            # nothing in it worth keeping, and a wrong entry here would report
            # an abandoned job as still running.
            self._own.clear()
            return len(stale)

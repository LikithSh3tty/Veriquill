"""Reading and writing the things a review gate needs to outlive a process.

Dossiers and machine scores are written once. Nothing here offers a way to edit
them, because a reviewer disagreeing with Veriquill must not be able to make it
look as though Veriquill never said it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veriquill.models import (
    ComparisonEntry,
    ComparisonRecord,
    DossierRecord,
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

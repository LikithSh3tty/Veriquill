"""Engine, session factory, and the one write helper the engines share."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from veriquill.findings import Finding
from veriquill.models import Base, EvidenceRecord, FindingRecord


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def store_findings(
    session: Session, repository_id: int, findings: Iterable[Finding]
) -> None:
    for finding in findings:
        record = FindingRecord(
            repository_id=repository_id,
            check_id=finding.check_id,
            severity=finding.severity,
            title=finding.title,
            rationale=finding.rationale,
            confidence=finding.confidence,
        )
        record.evidence = [
            EvidenceRecord(
                repo=ref.repo,
                path=ref.path,
                line=ref.line,
                commit_sha=ref.commit_sha,
                detail=ref.detail,
            )
            for ref in finding.evidence
        ]
        session.add(record)

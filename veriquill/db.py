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
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Add columns that exist in the model but not yet in the database.

    `create_all` creates tables and never alters them, so a column added to a
    model after someone already has a database is invisible to it and every
    read of that table fails. This is additive only: it never drops, renames, or
    retypes anything, so the worst it can do is leave a column NULL.

    That is the whole migration story here, deliberately. Anything that could
    lose data belongs in a real migration tool, and this project has no business
    pretending to be one.
    """
    with engine.begin() as connection:
        for table in Base.metadata.tables.values():
            existing = {
                row[1]
                for row in connection.exec_driver_sql(
                    f"PRAGMA table_info({table.name})"
                ).fetchall()
            }
            if not existing:
                continue
            for column in table.columns:
                if column.name in existing:
                    continue
                kind = column.type.compile(engine.dialect)
                connection.exec_driver_sql(
                    f"ALTER TABLE {table.name} ADD COLUMN {column.name} {kind}"
                )


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

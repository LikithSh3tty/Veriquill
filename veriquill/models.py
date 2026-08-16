"""Persistence schema.

`RepoFingerprint` is deliberately not scoped to a candidate: cross-profile
duplication detection has to compare a repository against every repository
ever ingested, for any candidate.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from veriquill.findings import Severity


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    tool_version: Mapped[str] = mapped_column(String(32))
    token_scope: Mapped[str | None] = mapped_column(String(255), default=None)

    candidates: Mapped[list["Candidate"]] = relationship(back_populates="run")


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(120), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"))

    run: Mapped[AnalysisRun] = relationship(back_populates="candidates")
    repositories: Mapped[list["Repository"]] = relationship(back_populates="candidate")


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    is_fork: Mapped[bool] = mapped_column(default=False)
    primary_language: Mapped[str | None] = mapped_column(String(64), default=None)
    total_loc: Mapped[int] = mapped_column(Integer, default=0)
    authored_loc: Mapped[int] = mapped_column(Integer, default=0)
    commit_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_error: Mapped[str | None] = mapped_column(Text, default=None)

    candidate: Mapped[Candidate] = relationship(back_populates="repositories")
    findings: Mapped[list["FindingRecord"]] = relationship(back_populates="repository")


class FindingRecord(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    check_id: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    title: Mapped[str] = mapped_column(String(255))
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)

    repository: Mapped[Repository] = relationship(back_populates="findings")
    evidence: Mapped[list["EvidenceRecord"]] = relationship(back_populates="finding")


class EvidenceRecord(Base):
    __tablename__ = "evidence_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    repo: Mapped[str] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(1024), default=None)
    line: Mapped[int | None] = mapped_column(Integer, default=None)
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    finding: Mapped[FindingRecord] = relationship(back_populates="evidence")


class RepoFingerprint(Base):
    __tablename__ = "repo_fingerprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    candidate_handle: Mapped[str] = mapped_column(String(120), index=True)
    file_hashes: Mapped[list[str]] = mapped_column(JSON)

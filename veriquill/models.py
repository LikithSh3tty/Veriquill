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


class RubricRecord(Base):
    """A rubric as it was when a comparison used it.

    Rubrics are versioned rather than edited: a comparison scored last week has
    to stay reproducible after the recruiter reweights the rubric.
    """

    __tablename__ = "rubrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    weights: Mapped[dict[str, float]] = mapped_column(JSON)
    minimum_bars: Mapped[dict[str, float]] = mapped_column(JSON)
    # Dimensions this team added, each with the check ids it reads. Stored with
    # the rubric rather than derived, because a comparison scored last week has
    # to stay reproducible even if the definition changes afterwards.
    custom_dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DossierRecord(Base):
    """A dossier exactly as the engines produced it. Written once, never edited."""

    __tablename__ = "dossiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_handle: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComparisonRecord(Base):
    """One ranked cohort, and whether a human has signed off on it yet."""

    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    rubric_id: Mapped[int] = mapped_column(ForeignKey("rubrics.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending_review")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    rubric: Mapped[RubricRecord] = relationship()
    entries: Mapped[list["ComparisonEntry"]] = relationship(back_populates="comparison")


class ComparisonEntry(Base):
    """One candidate inside a comparison.

    `machine_score` and `machine_rank` are what Veriquill said before any human
    touched it. Nothing in this codebase updates them after they are written.
    """

    __tablename__ = "comparison_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id"))
    dossier_id: Mapped[int] = mapped_column(ForeignKey("dossiers.id"))
    candidate_handle: Mapped[str] = mapped_column(String(120), index=True)
    machine_score: Mapped[dict] = mapped_column(JSON)
    machine_rank: Mapped[int | None] = mapped_column(Integer, default=None)

    comparison: Mapped[ComparisonRecord] = relationship(back_populates="entries")
    dossier: Mapped[DossierRecord] = relationship()


class ReviewAction(Base):
    """Append-only. Every human intervention, with who made it and why.

    There is no update or delete path for this table anywhere in the codebase.
    Replaying these rows in order reconstructs any state a comparison has held.
    """

    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id"), index=True)
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("comparison_entries.id"), default=None
    )
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str | None] = mapped_column(String(255), default=None)
    reason: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntakeJobRecord(Base):
    """An analysis started from the interface.

    Jobs used to live in a dict on the API process. That was defensible while a
    lost job cost a page refresh, but it was not what a lost job actually cost:
    a restart mid-analysis left the browser polling an id the server no longer
    knew, which reads as "this candidate was never submitted" rather than "this
    analysis was interrupted". Those are different facts and a hiring tool does
    not get to confuse them.

    Rows here are working state, not evidence. The dossier the job writes is
    what a decision rests on, and it lives in `dossiers`.
    """

    __tablename__ = "intake_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    handle: Mapped[str] = mapped_column(String(39), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    dossier_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

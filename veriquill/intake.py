"""Adding a candidate from the interface.

Analysing a portfolio means cloning every public repository and walking its
history, which takes minutes. A request that did that inline would sit open until
something in the middle timed out, so intake is a job: the caller gets an id
immediately and polls it.

Uploads are the input where the fairness controls matter most, so this module is
deliberately strict about them. It accepts a short allowlist of extensions, caps
the size, ignores whatever directory the client claimed the file came from, and
writes into a working directory the caller deletes afterwards. Nothing here
stores a résumé: the claim pipeline redacts protected attributes as it reads, and
the file itself is temporary.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

RESUME_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
LINKEDIN_SUFFIXES = {".csv", ".json"}

# GitHub's own rule: alphanumerics and single hyphens, no leading or trailing
# hyphen, 39 characters at most.
_HANDLE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

JobStatus = Literal["queued", "running", "done", "failed"]


class IntakeError(ValueError):
    """Raised when a candidate cannot be accepted, with the reason to show."""


@dataclass
class Job:
    id: str
    handle: str
    status: JobStatus = "queued"
    error: str | None = None
    dossier_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """What the interface may see. No filesystem paths, no document content."""
        return {
            "id": self.id,
            "handle": self.handle,
            "status": self.status,
            "error": self.error,
            "dossier_id": self.dossier_id,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobStore:
    """In-process job state.

    Intake jobs are transient by nature: what survives a restart is the dossier
    the job wrote, which lives in SQLite. A lost job record costs a page refresh,
    not evidence.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []

    def create(self, handle: str) -> Job:
        handle = (handle or "").strip()
        if not handle:
            raise IntakeError("enter a GitHub username")
        if not _HANDLE.match(handle):
            raise IntakeError(
                f"{handle!r} is not a GitHub username: letters, digits and single "
                "hyphens only, up to 39 characters"
            )

        job = Job(id=uuid.uuid4().hex, handle=handle)
        self._jobs[job.id] = job
        self._order.append(job.id)
        return job

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise IntakeError(f"no intake job {job_id!r}")
        return job

    def list(self) -> list[Job]:
        return [self._jobs[job_id] for job_id in reversed(self._order)]

    def start(self, job_id: str) -> Job:
        job = self.get(job_id)
        job.status = "running"
        return job

    def finish(self, job_id: str, dossier_id: int) -> Job:
        job = self.get(job_id)
        job.status = "done"
        job.dossier_id = dossier_id
        job.finished_at = datetime.now(timezone.utc)
        return job

    def fail(self, job_id: str, error: str) -> Job:
        job = self.get(job_id)
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        return job


def stage_upload(
    filename: str, content: bytes, workdir: Path, allowed: set[str]
) -> Path:
    """Write an uploaded document into `workdir`, or refuse it.

    Only the base name is honoured. A client-supplied path is not a location this
    server will write to, whatever it claims.
    """
    name = Path(filename or "").name
    suffix = Path(name).suffix.lower()

    if suffix not in allowed:
        raise IntakeError(
            f"{suffix or 'that file'} is not a supported format; expected "
            + ", ".join(sorted(allowed))
        )
    if not content:
        raise IntakeError(f"{name} is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise IntakeError(
            f"{name} is too large: {len(content) // 1024} KB, and the limit is "
            f"{MAX_UPLOAD_BYTES // 1024} KB"
        )

    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)
    return target

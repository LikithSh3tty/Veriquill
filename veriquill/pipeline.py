"""Fan-out over a candidate's repositories.

One repository failing never fails the candidate: the failure is recorded as
an error on that repository and the run continues.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from veriquill import __version__
from veriquill.codeeval.engine import run_codeeval
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Finding
from veriquill.github.client import GitHubClient
from veriquill.github.clone import CloneError, ephemeral_clone
from veriquill.github.history import read_history
from veriquill.github.ingest import fetch_identity, list_repositories
from veriquill.provenance.duplication import fingerprint_repo
from veriquill.provenance.engine import run_provenance

logger = logging.getLogger(__name__)


@dataclass
class RepoResult:
    full_name: str
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.full_name,
            "error": self.error,
            "findings": [
                {
                    "check_id": f.check_id,
                    "severity": f.severity.value,
                    "title": f.title,
                    "rationale": f.rationale,
                    "confidence": f.confidence,
                    "evidence": [
                        {
                            "repo": e.repo,
                            "path": e.path,
                            "line": e.line,
                            "commit_sha": e.commit_sha,
                            "detail": e.detail,
                        }
                        for e in f.evidence
                    ],
                }
                for f in self.findings
            ],
        }


@dataclass
class RunSummary:
    handle: str
    started_at: datetime
    finished_at: datetime | None = None
    repositories: list[RepoResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "tool_version": __version__,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "disclaimer": (
                "Findings are advisory and evidence-linked. They are questions for a "
                "human reviewer, never verdicts, and never proof of wrongdoing."
            ),
            "repositories": [r.to_dict() for r in self.repositories],
        }


async def _analyse_repo(
    repo: dict[str, Any],
    handle: str,
    identities: frozenset[str],
    settings: Settings,
    known_fingerprints: dict[str, list[str]],
    semaphore: asyncio.Semaphore,
) -> RepoResult:
    full_name = repo.get("full_name", "unknown")
    result = RepoResult(full_name=full_name)

    async with semaphore:
        try:
            async with ephemeral_clone(
                repo["clone_url"], settings.workdir, settings.clone_timeout_seconds
            ) as clone_path:
                ctx = RepoContext(
                    full_name=full_name,
                    path=clone_path,
                    candidate_handle=handle,
                    identities=identities,
                    commits=read_history(clone_path),
                    metadata=repo,
                )
                result.findings = run_provenance(ctx, settings, known_fingerprints)
                result.findings.extend(run_codeeval(ctx, settings))
                known_fingerprints[f"{handle}:{full_name}"] = fingerprint_repo(ctx)
        except CloneError as exc:
            result.error = str(exc)
        except Exception as exc:  # analysis failure is never evidence against anyone
            logger.exception("analysis failed for %s", full_name)
            result.error = f"analysis failed: {exc}"

    return result


async def analyse_candidate(
    handle: str,
    settings: Settings,
    client: GitHubClient | None = None,
    known_fingerprints: dict[str, list[str]] | None = None,
) -> RunSummary:
    settings.ensure_dirs()
    summary = RunSummary(handle=handle, started_at=datetime.now(timezone.utc))
    fingerprints = known_fingerprints if known_fingerprints is not None else {}
    active = client or GitHubClient(settings)

    async with active as connected:
        identity = await fetch_identity(connected, handle)
        repos = await list_repositories(connected, handle)

        semaphore = asyncio.Semaphore(settings.max_clone_concurrency)
        summary.repositories = list(
            await asyncio.gather(
                *(
                    _analyse_repo(
                        repo,
                        handle,
                        identity["identities"],
                        settings,
                        fingerprints,
                        semaphore,
                    )
                    for repo in repos
                )
            )
        )

    summary.finished_at = datetime.now(timezone.utc)
    return summary

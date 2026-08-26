"""Fan-out over a candidate's repositories.

One repository failing never fails the candidate: the failure is recorded as
an error on that repository and the run continues.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from veriquill import __version__
from veriquill.codeeval.detect import profile_repo
from veriquill.codeeval.engine import run_codeeval
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Finding
from veriquill.github.client import GitHubClient
from veriquill.github.clone import CloneError, ephemeral_clone, sweep_workdir
from veriquill.github.history import read_history
from veriquill.github.ingest import (
    attributed_identities,
    fetch_identity,
    list_repositories,
)
from veriquill.provenance.duplication import fingerprint_repo
from veriquill.provenance.engine import run_provenance
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.github.refs import account_fingerprint
from veriquill.relevance import select_repositories
from veriquill.vendored import is_vendored

logger = logging.getLogger(__name__)


def build_evidence(ctx: RepoContext, findings: list[Finding]) -> RepoEvidence:
    """Flatten what the engines learned into the shape reconciliation compares.

    Authorship share is measured against commits a person wrote. Counting
    automation in the denominator sent that share below the threshold
    reconciliation treats as support, and a candidate whose own project had
    two hundred Dependabot bumps had their resume claim to have built it
    returned as contradicted: the strongest thing this tool can say about a
    person, earned by keeping dependencies current.
    """
    authored = ctx.authored_commits
    authored_loc = sum(
        change.insertions
        for commit in authored
        for change in commit.files
        if not is_vendored(change.path)
    )
    profile = profile_repo(ctx.path)

    return RepoEvidence(
        full_name=ctx.full_name,
        description=str(ctx.metadata.get("description") or ""),
        topics=tuple(ctx.metadata.get("topics") or ()),
        languages=dict(profile.languages),
        authored_commits=len(authored),
        total_commits=len(ctx.human_commits),
        authored_loc=authored_loc,
        check_ids=tuple(f.check_id for f in findings),
    )


@dataclass
class RepoResult:
    full_name: str
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    evidence: RepoEvidence | None = None

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
    # Everything the account holds, so a partial read never looks like a full one.
    repositories_on_account: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)
    selection: list[dict[str, Any]] = field(default_factory=list)
    #: What the selected repositories' histories currently are, taken before
    #: anything was cloned. A later run that fingerprints the same is looking
    #: at the same histories and the same tool, so it can reuse the dossier.
    #: None means the question could not be answered, which is never read as
    #: an answer of no change.
    refs_fingerprint: str | None = None

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
            "repositories_on_account": self.repositories_on_account or len(self.repositories),
            "repositories_read": len(self.repositories),
            "repositories_skipped": [
                {
                    "repository": row["repository"].get("full_name")
                    or row["repository"].get("name"),
                    "reason": row["reason"],
                }
                for row in self.skipped
            ],
            "selection": [
                {
                    "repository": row["repository"].get("full_name")
                    or row["repository"].get("name"),
                    "reasons": row["reasons"],
                }
                for row in self.selection
            ],
            "repositories": [r.to_dict() for r in self.repositories],
        }


def _read_and_analyse(
    result: RepoResult,
    clone_path: Path,
    repo: dict[str, Any],
    handle: str,
    identities: frozenset[str],
    user_id: int | None,
    settings: Settings,
    known_fingerprints: dict[str, list[str]],
) -> None:
    """Everything that happens to a clone, none of which is asynchronous.

    Kept together so it can be handed to one thread. It mutates `result` in
    place rather than returning, because the caller already owns that object
    and a repository that fails partway should keep whatever it did manage.
    """
    full_name = repo.get("full_name", "unknown")
    ctx = RepoContext(
        full_name=full_name,
        path=clone_path,
        candidate_handle=handle,
        identities=identities,
        commits=read_history(clone_path),
        metadata=repo,
        user_id=user_id,
    )
    result.findings = run_provenance(ctx, settings, known_fingerprints)
    result.findings.extend(run_codeeval(ctx, settings))
    result.evidence = build_evidence(ctx, result.findings)
    known_fingerprints[f"{handle}:{full_name}"] = fingerprint_repo(ctx)

async def _analyse_repo(
    repo: dict[str, Any],
    handle: str,
    identities: frozenset[str],
    user_id: int | None,
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
                # In a thread, because none of it is asynchronous and all of
                # it is slow: git log over the whole history, bandit and ruff
                # as subprocesses, then a hash of every authored file. Run
                # directly on the loop it blocked every other repository's
                # clone, and their timeouts fired for work that was never
                # slow. Three repositories in a real portfolio were reported
                # as unclonable at three hundred seconds; each of them clones
                # by hand in under five.
                await asyncio.to_thread(
                    _read_and_analyse,
                    result,
                    clone_path,
                    repo,
                    handle,
                    identities,
                    user_id,
                    settings,
                    known_fingerprints,
                )
        except CloneError as exc:
            result.error = str(exc)
        except Exception as exc:  # analysis failure is never evidence against anyone
            logger.exception("analysis failed for %s", full_name)
            result.error = f"analysis failed: {exc}"

    return result


async def account_refs_fingerprint(
    handle: str,
    settings: Settings,
    client: GitHubClient | None = None,
    job_description: str = "",
) -> str | None:
    """What this candidate's selected repositories currently hold, without cloning.

    Two REST calls and one ls-remote per repository, against the minutes a
    full analysis costs. A caller holding a dossier stamped with the same
    value is holding one built from the same histories by the same code.

    None means the question could not be answered, and an unanswered question
    is never an answer of no change.
    """
    settings.ensure_dirs()
    active = client or GitHubClient(settings)

    async with active as connected:
        repos = await list_repositories(connected, handle)
        selected, _skipped = select_repositories(
            repos,
            job_description,
            limit=settings.relevance_limit,
            threshold=settings.relevance_threshold,
        )

    return await account_fingerprint(
        {
            str(row["repository"].get("full_name") or row["repository"].get("name")): str(
                row["repository"]["clone_url"]
            )
            for row in selected
            if row["repository"].get("clone_url")
        },
        settings.clone_timeout_seconds,
    )

async def analyse_candidate(
    handle: str,
    settings: Settings,
    client: GitHubClient | None = None,
    known_fingerprints: dict[str, list[str]] | None = None,
    aliases: frozenset[str] = frozenset(),
    job_description: str = "",
) -> RunSummary:
    settings.ensure_dirs()
    # Reclaim what earlier runs could not. A killed process never reaches the
    # cleanup in ephemeral_clone, and nothing else ever looked.
    sweep_workdir(settings.workdir)
    summary = RunSummary(handle=handle, started_at=datetime.now(timezone.utc))
    fingerprints = known_fingerprints if known_fingerprints is not None else {}
    active = client or GitHubClient(settings)

    async with active as connected:
        identity = await fetch_identity(connected, handle, aliases)
        repos = await list_repositories(connected, handle)
        summary.repositories_on_account = len(repos)

        # A large account is read in part, most-relevant first. What is skipped
        # is named and lowers coverage; it is never treated as a finding.
        selected, skipped = select_repositories(
            repos,
            job_description,
            limit=settings.relevance_limit,
            threshold=settings.relevance_threshold,
        )
        summary.selection = selected
        summary.skipped = skipped
        repos = [row["repository"] for row in selected]

        # Ask GitHub who it attributes these commits to, rather than relying
        # only on the identities guessed from the profile. A candidate signing
        # with a verified but private address matches none of the guesses, and
        # reads as having authored none of their own work.
        identities = frozenset(identity["identities"]) | await attributed_identities(
            connected, [str(repo.get("full_name") or repo.get("name")) for repo in repos], handle
        )

        # Asked before anything is cloned, so a caller holding a dossier with
        # this fingerprint can skip the clones entirely. One ls-remote per
        # repository against minutes of cloning and history walking.
        summary.refs_fingerprint = await account_fingerprint(
            {
                str(repo.get("full_name") or repo.get("name")): str(repo["clone_url"])
                for repo in repos
                if repo.get("clone_url")
            },
            settings.clone_timeout_seconds,
        )

        semaphore = asyncio.Semaphore(settings.max_clone_concurrency)
        summary.repositories = list(
            await asyncio.gather(
                *(
                    _analyse_repo(
                        repo,
                        handle,
                        identities,
                        identity.get("user_id"),
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


async def build_candidate_dossier(
    handle: str,
    settings: Settings,
    resume: Path | None = None,
    linkedin: Path | None = None,
    job_description: str = "",
    aliases: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Analyse a candidate and assemble their dossier.

    The CLI and the HTTP intake both come through here, so a candidate added from
    the interface is the same artifact as one added from a terminal.

    `aliases` carries the other names a candidate's commits are signed with: a
    previous GitHub login, or the address a machine's git config happens to
    write. Without them a repository the candidate genuinely wrote can read as
    somebody else's work, which is the most damaging thing this tool can get
    wrong. The parameter existed here before anything could reach it.
    """
    from veriquill.claims.engine import collect_claims
    from veriquill.dossier import build_dossier
    from veriquill.reconcile.engine import reconcile

    summary = await analyse_candidate(
        handle, settings, aliases=aliases, job_description=job_description
    )
    claim_set = collect_claims(settings, resume=resume, linkedin=linkedin)
    evidence = [r.evidence for r in summary.repositories if r.evidence is not None]

    report = build_dossier(
        handle,
        summary.repositories,
        reconcile(claim_set.claims, evidence),
        repositories_on_account=summary.repositories_on_account,
        skipped=summary.to_dict()["repositories_skipped"],
    )
    report["claims_examined"] = len(claim_set.claims)
    report["claim_errors"] = claim_set.errors
    # What the histories were when this was built. A later run that reads the
    # same fingerprint is looking at the same work through the same code.
    report["refs_fingerprint"] = summary.refs_fingerprint
    return report

"""Cross-profile duplication.

Shared code is usually joint work, which is why this emits INFO. It is context
for the recruiter, never an accusation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.vendored import authored_files

_MIN_FILES = 3


def fingerprint_repo(ctx: RepoContext) -> list[str]:
    """Content hashes of authored files, order-independent."""
    hashes: list[str] = []
    for relative in authored_files(ctx.path):
        absolute: Path = ctx.path / relative
        try:
            content = absolute.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256()
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(content)
        hashes.append(digest.hexdigest())
    return sorted(hashes)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def check_duplication(
    ctx: RepoContext, settings: Settings, known: dict[str, list[str]]
) -> list[Finding]:
    mine = set(fingerprint_repo(ctx))
    if len(mine) < _MIN_FILES:
        return []

    findings: list[Finding] = []
    for key, hashes in known.items():
        handle, _, repo_name = key.partition(":")
        if handle == ctx.candidate_handle:
            continue
        overlap = _jaccard(mine, set(hashes))
        if overlap < settings.duplication_jaccard:
            continue
        findings.append(
            Finding(
                check_id="provenance.cross_profile_duplicate",
                severity=Severity.INFO,
                title="Codebase also appears on another profile",
                rationale=(
                    f"{overlap:.0%} of authored files are identical to {repo_name}, "
                    "previously analysed for another candidate. Joint projects "
                    "legitimately produce this."
                ),
                confidence=overlap,
                evidence=(
                    EvidenceRef(
                        repo=ctx.full_name,
                        detail=f"matches {repo_name} ({overlap:.0%} of files)",
                    ),
                ),
            )
        )
    return findings

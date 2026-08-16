"""Runs every provenance check and orders the results by severity.

Checks are advisory. Nothing here disqualifies a candidate, and one check
raising an exception must not lose the findings of the others.
"""

from __future__ import annotations

import logging

from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Finding
from veriquill.provenance import (
    check_bulk_dump,
    check_cadence,
    check_contribution,
    check_duplication,
    check_fork_origin,
    check_inflation,
)

logger = logging.getLogger(__name__)

_CHECKS = (
    check_cadence,
    check_bulk_dump,
    check_fork_origin,
    check_inflation,
    check_contribution,
)


def run_provenance(
    ctx: RepoContext,
    settings: Settings,
    known_fingerprints: dict[str, list[str]],
) -> list[Finding]:
    findings: list[Finding] = []

    for check in _CHECKS:
        try:
            findings.extend(check(ctx, settings))
        except Exception:  # one failing check must not silence the others
            logger.exception(
                "provenance check %s failed on %s", check.__name__, ctx.full_name
            )

    try:
        findings.extend(check_duplication(ctx, settings, known_fingerprints))
    except Exception:
        logger.exception("duplication check failed on %s", ctx.full_name)

    return sorted(findings, key=lambda f: (f.severity.rank, f.check_id))

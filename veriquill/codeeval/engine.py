"""Runs every code-evaluation analyser.

The engine is explicit about what it did not analyse. Silence about a language
would read as a clean bill of health, which would be dishonest.
"""

from __future__ import annotations

import logging

from veriquill.codeeval.complexity import check_complexity
from veriquill.codeeval.detect import DEEPLY_ANALYSED, LanguageProfile, profile_repo
from veriquill.codeeval.golang import (
    check_go_complexity,
    check_go_error_handling,
    check_go_security,
    check_go_tests,
)
from veriquill.codeeval.java import (
    check_java_complexity,
    check_java_exception_handling,
    check_java_security,
    check_java_tests,
)
from veriquill.codeeval.reviewer import DesignReviewer
from veriquill.codeeval.security import check_security
from veriquill.codeeval.structure import check_structure
from veriquill.codeeval.style import check_style
from veriquill.codeeval.tests import check_tests
from veriquill.codeeval.typescript import (
    check_typescript_complexity,
    check_typescript_security,
    check_typescript_tests,
)
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

logger = logging.getLogger(__name__)

_ANALYSERS = (
    check_complexity,
    check_security,
    check_style,
    check_tests,
    check_structure,
    check_typescript_complexity,
    check_typescript_security,
    check_typescript_tests,
    check_go_complexity,
    check_go_security,
    check_go_tests,
    check_go_error_handling,
    check_java_complexity,
    check_java_security,
    check_java_tests,
    check_java_exception_handling,
)


def coverage_note(profile: LanguageProfile, repo_name: str = "") -> Finding | None:
    shallow = sorted(set(profile.languages) - DEEPLY_ANALYSED)
    if not shallow:
        return None
    return Finding(
        check_id="codeeval.coverage_note",
        severity=Severity.INFO,
        title="Some languages were not deeply analysed",
        rationale=(
            f"Analysed in depth: {', '.join(sorted(DEEPLY_ANALYSED))}. These "
            f"languages were detected and counted only: {', '.join(shallow)}. No "
            "quality judgment is made about them, in either direction."
        ),
        confidence=1.0,
        evidence=(
            EvidenceRef(
                repo=repo_name,
                detail=f"detected languages: {', '.join(sorted(profile.languages))}",
            ),
        ),
    )


def run_codeeval(ctx: RepoContext, settings: Settings) -> list[Finding]:
    profile = profile_repo(ctx.path)
    if not profile.languages:
        return []

    findings: list[Finding] = []
    for analyser in _ANALYSERS:
        try:
            findings.extend(analyser(ctx, profile, settings))
        except Exception:
            logger.exception("analyser %s failed on %s", analyser.__name__, ctx.full_name)

    # Judgment runs last and only when switched on, so the deterministic
    # findings above are never contingent on a model being reachable.
    reviewer = DesignReviewer(settings)
    if reviewer.available:
        try:
            findings.extend(reviewer.review(ctx, profile))
        except Exception:
            logger.exception("design review failed on %s", ctx.full_name)

    note = coverage_note(profile, ctx.full_name)
    if note is not None:
        findings.append(note)

    return sorted(findings, key=lambda f: (f.severity.rank, f.check_id))

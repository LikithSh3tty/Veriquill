"""One scorer per rubric dimension, each reading a stored dossier.

Every scorer returns a score, the share of the portfolio it was able to look at,
and the evidence behind both. Absence of evidence lowers coverage. It never
lowers a score: "we could not tell" and "this is weak" are different sentences,
and a recruiter has to be able to tell them apart.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from veriquill.findings import EvidenceRef
from veriquill.rank.models import DimensionScore
from veriquill.rubric import DIMENSIONS

SEVERITY_PENALTY: dict[str, float] = {
    "critical": 1.0,
    "high": 0.6,
    "medium": 0.3,
    "low": 0.15,
    "info": 0.0,
}

PROVENANCE_PREFIX = "provenance."
CONTRADICTION_CHECK = "reconciliation.contradicted_claim"
CODE_QUALITY_CHECKS = frozenset(
    {
        "codeeval.high_complexity",
        "codeeval.lint_debt",
        "codeeval.unreferenced_modules",
    }
)
TEST_CHECKS = frozenset({"codeeval.no_tests", "codeeval.trivial_tests"})
SECURITY_PREFIX = "codeeval.security."

FULL_BREADTH_REPOS = 5
CONTRADICTION_WEIGHT = 2.0


def _repos(count: int) -> str:
    """Plural that reads like English: this string reaches a recruiter's screen."""
    return "1 repository" if count == 1 else f"{count} repositories"


def _coverage(dossier: dict[str, Any]) -> dict[str, int]:
    return dossier.get("analysis_coverage") or {}


def _live_flags(
    dossier: dict[str, Any], dismissed: frozenset[str], predicate: Callable[[str], bool]
) -> list[dict[str, Any]]:
    return [
        flag
        for flag in dossier.get("red_flag_register") or []
        if flag.get("flag_id") not in dismissed and predicate(str(flag.get("check_id", "")))
    ]


def _penalty(flags: Iterable[dict[str, Any]]) -> float:
    return sum(
        SEVERITY_PENALTY.get(str(flag.get("severity")), 0.3)
        * float(flag.get("confidence", 1.0))
        for flag in flags
    )


def _flag_refs(flags: Iterable[dict[str, Any]]) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for flag in flags:
        for ref in flag.get("evidence") or []:
            refs.append(
                EvidenceRef(
                    repo=str(ref.get("repo") or ""),
                    path=ref.get("path"),
                    line=ref.get("line"),
                    commit_sha=ref.get("commit_sha"),
                    detail=f"{flag.get('check_id')}: {ref.get('detail') or flag.get('title')}",
                )
            )
    return tuple(refs)


def _repo_refs(dossier: dict[str, Any], detail: str) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(repo=str(row.get("repository") or ""), detail=detail)
        for row in dossier.get("code_quality_snapshot") or []
    )


def _unmeasured(dimension: str, basis: str) -> DimensionScore:
    return DimensionScore(
        dimension=dimension, score=None, coverage=0.0, evidence=(), basis=basis
    )


def _from_penalty(
    dimension: str,
    dossier: dict[str, Any],
    flags: list[dict[str, Any]],
    scale: int,
    coverage: float,
    clean_detail: str,
) -> DimensionScore:
    """Turn flags into a score in [0, 1], normalised by how much was analysed."""
    penalty = min(1.0, _penalty(flags) / max(1, scale))
    evidence = _flag_refs(flags) or _repo_refs(dossier, clean_detail)
    if not evidence:
        return _unmeasured(dimension, "no repository could be analysed")

    basis = (
        f"{len(flags)} flag(s) across {_repos(scale)} analysed"
        if flags
        else clean_detail
    )
    return DimensionScore(
        dimension=dimension,
        score=round(1.0 - penalty, 6),
        coverage=coverage,
        evidence=evidence,
        basis=basis,
    )


def score_authenticity(dossier: dict[str, Any], dismissed: frozenset[str]) -> DimensionScore:
    counts = _coverage(dossier)
    considered = counts.get("repositories_considered", 0)
    analysed = counts.get("repositories_analysed", 0)
    if analysed == 0:
        return _unmeasured(
            "authenticity",
            "no repository could be cloned and read, so authenticity was not measured",
        )

    flags = _live_flags(
        dossier,
        dismissed,
        lambda check: check.startswith(PROVENANCE_PREFIX) or check == CONTRADICTION_CHECK,
    )
    return _from_penalty(
        "authenticity",
        dossier,
        flags,
        analysed,
        min(1.0, analysed / max(1, considered)),
        f"commit history read for {_repos(analysed)}, no authenticity flag raised",
    )


def _codeeval_dimension(
    dimension: str,
    dossier: dict[str, Any],
    dismissed: frozenset[str],
    predicate: Callable[[str], bool],
    clean_detail: str,
) -> DimensionScore:
    counts = _coverage(dossier)
    deep = counts.get("repositories_deep_analysed", 0)
    authored = counts.get("repositories_with_authored_code", 0)
    if deep == 0:
        return _unmeasured(
            dimension,
            "no repository was analysed in depth; Python, TypeScript and JavaScript are "
            "analysed in depth, and no quality judgment is made about other languages "
            "in either direction",
        )
    return _from_penalty(
        dimension,
        dossier,
        _live_flags(dossier, dismissed, predicate),
        deep,
        min(1.0, deep / max(1, authored)),
        clean_detail,
    )


def score_code_quality(dossier: dict[str, Any], dismissed: frozenset[str]) -> DimensionScore:
    return _codeeval_dimension(
        "code_quality",
        dossier,
        dismissed,
        lambda check: check in CODE_QUALITY_CHECKS,
        "static analysis found no complexity, lint, or dead-module problem",
    )


def score_test_quality(dossier: dict[str, Any], dismissed: frozenset[str]) -> DimensionScore:
    return _codeeval_dimension(
        "test_quality",
        dossier,
        dismissed,
        lambda check: check in TEST_CHECKS,
        "tests were present and their assertions were not trivial",
    )


def score_security(dossier: dict[str, Any], dismissed: frozenset[str]) -> DimensionScore:
    return _codeeval_dimension(
        "security",
        dossier,
        dismissed,
        lambda check: check.startswith(SECURITY_PREFIX),
        "no security-hygiene finding was raised",
    )


def score_claim_corroboration(
    dossier: dict[str, Any], dismissed: frozenset[str]
) -> DimensionScore:
    counts = _coverage(dossier)
    total = counts.get("claims_total", 0)
    resolved = counts.get("claims_resolved", 0)
    if total == 0:
        return _unmeasured(
            "claim_corroboration",
            "no claim document was supplied, so nothing could be reconciled",
        )
    if resolved == 0:
        return _unmeasured(
            "claim_corroboration",
            f"none of the {total} claim(s) could be confirmed or denied by a public artifact",
        )

    verdicts = (dossier.get("claim_vs_evidence") or {}).get("counts") or {}
    corroborated = int(verdicts.get("corroborated", 0))
    contradicted = int(verdicts.get("contradicted", 0))
    raw = (corroborated - CONTRADICTION_WEIGHT * contradicted) / resolved
    score = min(1.0, max(0.0, raw))

    rows = (dossier.get("claim_vs_evidence") or {}).get("rows") or []
    evidence = tuple(
        EvidenceRef(repo=str(repo), detail=str(row.get("claim") or "claim"))
        for row in rows
        for repo in (row.get("repositories") or [])
    )
    if not evidence:
        evidence = _repo_refs(dossier, "claims reconciled against this repository")
    if not evidence:
        return _unmeasured(
            "claim_corroboration", "claims were resolved but no repository was cited"
        )

    return DimensionScore(
        dimension="claim_corroboration",
        score=round(score, 6),
        coverage=round(resolved / total, 6),
        evidence=evidence,
        basis=(
            f"{corroborated} corroborated, {contradicted} contradicted, "
            f"{resolved} of {total} claim(s) resolvable"
        ),
    )


def score_breadth(dossier: dict[str, Any], dismissed: frozenset[str]) -> DimensionScore:
    counts = _coverage(dossier)
    analysed = counts.get("repositories_analysed", 0)
    authored = counts.get("repositories_with_authored_code", 0)
    if analysed == 0:
        return _unmeasured("breadth", "no repository could be analysed")

    evidence = _repo_refs(dossier, "analysed repository")
    if not evidence:
        return _unmeasured("breadth", "no repository could be analysed")

    return DimensionScore(
        dimension="breadth",
        score=round(min(1.0, authored / FULL_BREADTH_REPOS), 6),
        coverage=1.0,
        evidence=evidence,
        basis=(
            f"{_repos(authored)} hold authored code; "
            f"{FULL_BREADTH_REPOS} or more scores full marks"
        ),
    )


SCORERS: tuple[Callable[[dict[str, Any], frozenset[str]], DimensionScore], ...] = (
    score_authenticity,
    score_code_quality,
    score_claim_corroboration,
    score_test_quality,
    score_security,
    score_breadth,
)


def score_dimensions(
    dossier: dict[str, Any], dismissed: frozenset[str] = frozenset()
) -> tuple[DimensionScore, ...]:
    """Score every dimension once, returned in the rubric's canonical order."""
    scored: dict[str, DimensionScore] = {}
    for scorer in SCORERS:
        result = scorer(dossier, dismissed)
        scored[result.dimension] = result
    return tuple(scored[dimension] for dimension in DIMENSIONS)

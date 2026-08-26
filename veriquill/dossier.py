"""The consolidated summary a recruiter reads (specification §9).

Nothing is hidden. Every red flag is listed with its severity and evidence,
next to the verified strengths and the open questions. The verdict band is a
confidence-qualified sentence, never a bare score, and it is never a decision:
the human reading this makes the decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from veriquill.codeeval.detect import DEEPLY_ANALYSED
from veriquill.findings import Severity
from veriquill.reconcile.models import Reconciliation, Verdict


def _flag_id(flag: dict[str, Any], ordinal: int) -> str:
    """A stable handle a reviewer can dismiss by reference.

    Derived from the content of the flag, so the same finding keeps the same id
    across runs and machines. The ordinal only separates two genuinely identical
    flags inside one register.
    """
    material = json.dumps(
        {
            "check_id": flag["check_id"],
            "title": flag["title"],
            "evidence": flag["evidence"],
            "ordinal": ordinal,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _claim_payload(reconciliation: Reconciliation) -> dict[str, Any]:
    claim = reconciliation.claim
    assert claim is not None
    return {
        "claim": claim.text,
        "kind": claim.kind.value,
        "source": {
            "document": claim.source.document,
            "locator": claim.source.locator,
            "excerpt": claim.source.excerpt,
        },
        "rationale": reconciliation.rationale,
        "confidence": reconciliation.confidence,
        "repositories": [e.full_name for e in reconciliation.evidence],
    }


def _verified_strengths(reconciliations: list[Reconciliation]) -> list[dict[str, Any]]:
    strengths: list[dict[str, Any]] = []

    for result in reconciliations:
        if result.verdict is Verdict.CORROBORATED:
            strengths.append(_claim_payload(result))
        elif result.verdict is Verdict.UNDISCLOSED:
            strengths.append(
                {
                    "claim": None,
                    "kind": "undisclosed",
                    "source": None,
                    "rationale": result.rationale,
                    "confidence": result.confidence,
                    "repositories": [e.full_name for e in result.evidence],
                }
            )

    return strengths


def _red_flags(
    repo_results: list[Any], reconciliations: list[Reconciliation]
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    # A claim contradicted by the evidence is the most serious thing Veriquill
    # can surface, so it leads the register.
    for result in reconciliations:
        if result.verdict is not Verdict.CONTRADICTED:
            continue
        claim = result.claim
        assert claim is not None
        flags.append(
            {
                "severity": Severity.CRITICAL.value,
                "rank": Severity.CRITICAL.rank,
                "check_id": "reconciliation.contradicted_claim",
                "title": f"Claim contradicted by evidence: {claim.text}",
                "rationale": result.rationale,
                "confidence": result.confidence,
                "evidence": [
                    {
                        "repo": e.full_name,
                        "detail": (
                            f"{e.authored_commits} of {e.total_commits} commits "
                            "authored by the candidate"
                        ),
                    }
                    for e in result.evidence
                ]
                or [
                    {
                        "repo": None,
                        "detail": f"{claim.source.document} {claim.source.locator}",
                    }
                ],
            }
        )

    for repo in repo_results:
        for finding in getattr(repo, "findings", []):
            if finding.severity is Severity.INFO:
                continue
            flags.append(
                {
                    "severity": finding.severity.value,
                    "rank": finding.severity.rank,
                    "check_id": finding.check_id,
                    "title": finding.title,
                    "rationale": finding.rationale,
                    "confidence": finding.confidence,
                    "evidence": [
                        {
                            "repo": ref.repo,
                            "path": ref.path,
                            "line": ref.line,
                            "commit_sha": ref.commit_sha,
                            "detail": ref.detail,
                        }
                        for ref in finding.evidence
                    ],
                }
            )

    flags.sort(key=lambda f: (f["rank"], f["check_id"]))
    seen: dict[str, int] = {}
    for flag in flags:
        flag.pop("rank")
        key = f"{flag['check_id']}:{flag['title']}"
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        flag["flag_id"] = _flag_id(flag, ordinal)
    return flags


def _analysis_coverage(
    repo_results: list[Any],
    reconciliations: list[Reconciliation],
    repositories_on_account: int = 0,
) -> dict[str, int]:
    """What the run was actually able to look at.

    Ranking reads a stored dossier, not a live run, so the dossier has to carry
    its own coverage figures. A repository nobody could analyse lowers coverage;
    it is never scored as a failing repository.
    """
    analysed = [r for r in repo_results if not getattr(r, "error", None)]
    with_evidence = [r for r in analysed if getattr(r, "evidence", None) is not None]

    return {
        # What the account holds, not what we managed to read. Reading five of
        # twenty-one is a coverage fact, and the confidence band must feel it.
        "repositories_considered": max(repositories_on_account, len(repo_results)),
        "repositories_analysed": len(analysed),
        "repositories_with_authored_code": sum(
            1 for r in with_evidence if r.evidence.authored_loc > 0
        ),
        # Any language an analyser actually inspects counts here. Restricting it
        # to Python meant a TypeScript portfolio measured as unreadable and
        # carried a wide confidence band for it, which the fairness audit named
        # as the most likely route to disparate impact in this design.
        "repositories_deep_analysed": sum(
            1 for r in with_evidence if DEEPLY_ANALYSED.intersection(r.evidence.languages)
        ),
        "claims_total": sum(1 for r in reconciliations if r.claim is not None),
        "claims_resolved": sum(
            1
            for r in reconciliations
            if r.verdict in (Verdict.CORROBORATED, Verdict.CONTRADICTED)
        ),
    }


def _code_quality_snapshot(repo_results: list[Any]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []

    for repo in repo_results:
        findings = list(getattr(repo, "findings", []))
        if getattr(repo, "error", None):
            continue
        snapshot.append(
            {
                "repository": repo.full_name,
                "checks": sorted(
                    {f.check_id for f in findings if f.check_id.startswith("codeeval.")}
                ),
                "authenticity_checks": sorted(
                    {
                        f.check_id
                        for f in findings
                        if f.check_id.startswith("provenance.")
                    }
                ),
            }
        )

    return snapshot


def _open_questions(
    reconciliations: list[Reconciliation], flags: list[dict[str, Any]]
) -> list[str]:
    questions: list[str] = []

    for result in reconciliations:
        claim = result.claim
        if result.verdict is Verdict.UNVERIFIABLE and claim is not None:
            questions.append(
                f"Ask the candidate to walk through {claim.text!r} "
                f"({claim.source.document} {claim.source.locator}); no public "
                "artifact confirms or denies it."
            )
        elif result.verdict is Verdict.CONTRADICTED and claim is not None:
            questions.append(
                f"Ask what the candidate's specific contribution to {claim.text!r} "
                "was; the commit history does not show them authoring it."
            )
        elif result.verdict is Verdict.UNDISCLOSED:
            repos = ", ".join(e.full_name for e in result.evidence)
            questions.append(
                f"Ask about {repos}, which the candidate did not mention."
            )

    for flag in flags:
        if flag["check_id"] == "provenance.bulk_dump":
            questions.append(
                "Ask how the code in the flagged repository was developed before "
                "it was pushed; a single large import looks the same as a "
                "fabricated history."
            )

    return questions


def build_dossier(
    handle: str,
    repo_results: list[Any],
    reconciliations: list[Reconciliation],
    repositories_on_account: int = 0,
    skipped: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    flags = _red_flags(repo_results, reconciliations)
    strengths = _verified_strengths(reconciliations)

    counts = {v.value: 0 for v in Verdict}
    for result in reconciliations:
        counts[result.verdict.value] += 1

    critical_or_high = [f for f in flags if f["severity"] in ("critical", "high")]
    if critical_or_high:
        band = "significant questions to resolve before proceeding"
    elif counts["contradicted"]:
        band = "at least one claim is not supported by the evidence"
    elif strengths:
        band = "evidence supports the claims made"
    else:
        band = "insufficient evidence to say either way"

    evidence_coverage = 1.0 if all(f["evidence"] for f in flags) else 0.0

    errored = [
        r for r in repo_results if getattr(r, "error", None)
    ]
    notes = [
        "Veriquill supports a hiring decision and does not make one. Every "
        "finding here is advisory and is a question for a human reviewer.",
        "Flags are not proof of wrongdoing. Innocent explanations exist for "
        "every check: local development then a one-shot import, an account "
        "migration, a different git email, joint or employer-owned work.",
        "No protected attribute is inferred or used. Nothing was scraped; "
        "LinkedIn data is only ever read from a candidate-provided export.",
        "Python is analysed through its syntax tree. TypeScript, JavaScript, "
        "Go and Java are read textually, which finds less and can miss what a "
        "parser would catch. Every other language is counted and not judged, "
        "so silence about one is not a finding about it.",
    ]
    if skipped:
        names = ", ".join(str(row.get("repository")) for row in skipped[:5])
        more = "" if len(skipped) <= 5 else f", and {len(skipped) - 5} more"
        notes.append(
            f"{len(skipped)} repositor{'y' if len(skipped) == 1 else 'ies'} on this "
            f"account were not read: {names}{more}. They were outside the most "
            "relevant selection for this posting. Coverage below counts the whole "
            "account, so the confidence band reflects what was left unread."
        )

    for repo in errored:
        notes.append(
            f"Not analysed: {repo.full_name} ({repo.error}). This is recorded "
            "as a gap in coverage and is not held against the candidate."
        )

    return {
        "handle": handle,
        "verdict_band": {
            "band": band,
            "summary": (
                f"{counts['corroborated']} claim(s) corroborated, "
                f"{counts['contradicted']} contradicted, "
                f"{counts['unverifiable']} unverifiable, "
                f"{counts['undisclosed']} undisclosed strength(s); "
                f"{len(critical_or_high)} high-severity flag(s)."
            ),
            "confidence": "low" if not reconciliations and not flags else "moderate",
            "is_decision": False,
        },
        "verified_strengths": strengths,
        "red_flag_register": flags,
        "claim_vs_evidence": {
            "counts": counts,
            "rows": [_claim_payload(r) for r in reconciliations if r.claim is not None],
        },
        "code_quality_snapshot": _code_quality_snapshot(repo_results),
        "gaps_and_open_questions": _open_questions(reconciliations, flags),
        "provenance_and_fairness_notes": notes,
        "analysis_coverage": _analysis_coverage(
            repo_results, reconciliations, repositories_on_account
        ),
        "repositories_not_read": list(skipped or []),
        "evidence_coverage": evidence_coverage,
    }

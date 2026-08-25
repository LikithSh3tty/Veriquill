"""Runs the claim workers and merges what they produce.

The resume and LinkedIn workers are independent; either can be absent. A
source that cannot be read is recorded as an error against that source, never
as a claim and never as a failure of the whole run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from veriquill.claims.documents import load_document
from veriquill.claims.linkedin import load_linkedin_export
from veriquill.claims.models import Claim, ClaimKind
from veriquill.claims.refine import ClaimRefiner
from veriquill.claims.resume import parse_resume
from veriquill.config import Settings
from veriquill.fairness.signals import redact_document, redact_prose, scan_lines

logger = logging.getLogger(__name__)


@dataclass
class ClaimSet:
    claims: list[Claim] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    refined: bool = False
    redactions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_count": len(self.claims),
            "refined_by_model": self.refined,
            "errors": list(self.errors),
            "redactions": list(self.redactions),
            "disclaimer": (
                "These are the candidate's own statements, not verified facts. "
                "They carry weight only once reconciled against evidence."
            ),
            "claims": [
                {
                    "kind": c.kind.value,
                    "text": c.text,
                    "subject": c.subject,
                    "confidence": c.confidence,
                    "source": {
                        "document": c.source.document,
                        "locator": c.source.locator,
                        "excerpt": c.source.excerpt,
                    },
                }
                for c in self.claims
            ],
        }


def _dedupe(claims: list[Claim]) -> list[Claim]:
    """Keep the first claim seen for each (kind, subject-or-text).

    The resume is collected first, so where the same skill appears in both the
    resume and a LinkedIn export the resume's richer wording survives.
    """
    kept: list[Claim] = []
    seen: set[tuple[ClaimKind, str]] = set()
    verbatim: set[tuple[str, str, str]] = set()

    for claim in claims:
        key = (claim.kind, (claim.subject or claim.text).strip().lower())
        if key in seen:
            continue
        # The same sentence classified two ways is still one statement. Without
        # this the dossier raises the same question twice, once per kind.
        exact = (
            claim.source.document,
            claim.source.locator,
            claim.text.strip().lower(),
        )
        if exact in verbatim:
            continue
        seen.add(key)
        verbatim.add(exact)
        kept.append(claim)

    return kept


def _claim_texts(claims: list[Claim]) -> list[str]:
    """Every string a claim carries, so a scan sees what a reader would."""
    return [f"{claim.text} {claim.source.excerpt}" for claim in claims]


def _redacted(claim: Claim) -> Claim:
    """The same claim with every protected value removed.

    Both the text and the quoted excerpt, because the excerpt is what the
    review screen shows and what the dossier stores. Redacting one and not
    the other would move the leak rather than close it.
    """
    return replace(
        claim,
        text=redact_prose(claim.text),
        source=replace(claim.source, excerpt=redact_prose(claim.source.excerpt)),
    )

def collect_claims(
    settings: Settings,
    resume: str | Path | None = None,
    linkedin: str | Path | None = None,
    refiner: ClaimRefiner | None = None,
) -> ClaimSet:
    result = ClaimSet()
    collected: list[Claim] = []

    if resume is not None:
        try:
            document = load_document(Path(resume))
            # Redaction happens before parsing and before the refiner, so no
            # protected attribute reaches a claim, a model, or a log.
            document, removed = redact_document(document)
            result.redactions.extend(
                {
                    "category": match.category,
                    "line": match.line,
                    "document": match.document,
                    "note": match.describe(),
                }
                for match in removed
            )
            structural = parse_resume(document)
            collected.extend(structural)

            active = refiner if refiner is not None else ClaimRefiner(settings)
            if active.available:
                extra = active.refine(document, existing=structural)
                collected.extend(extra)
                result.refined = True
        except Exception as exc:
            logger.exception("resume parsing failed for %s", resume)
            result.errors.append(f"resume {Path(resume).name}: {exc}")

    if linkedin is not None:
        try:
            # Redacted like the resume, and for the same reason. A LinkedIn
            # export carries a Birth Date column outright, and a position
            # summary is free text in which people state nationality,
            # marital status and religion. Without this the claim, its
            # quoted excerpt, the stored dossier and the reviewer's screen
            # all carried whatever the export held.
            entries = load_linkedin_export(linkedin)
            result.redactions.extend(
                {
                    "category": match.category,
                    "line": match.line,
                    "document": match.document,
                    "note": match.describe(),
                }
                for match in scan_lines(_claim_texts(entries), "linkedin")
            )
            collected.extend(_redacted(claim) for claim in entries)
        except Exception as exc:
            result.errors.append(f"linkedin: {exc}")

    result.claims = _dedupe(collected)
    return result

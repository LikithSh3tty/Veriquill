"""Runs the claim workers and merges what they produce.

The resume and LinkedIn workers are independent; either can be absent. A
source that cannot be read is recorded as an error against that source, never
as a claim and never as a failure of the whole run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veriquill.claims.documents import load_document
from veriquill.claims.linkedin import load_linkedin_export
from veriquill.claims.models import Claim, ClaimKind
from veriquill.claims.refine import ClaimRefiner
from veriquill.claims.resume import parse_resume
from veriquill.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ClaimSet:
    claims: list[Claim] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    refined: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_count": len(self.claims),
            "refined_by_model": self.refined,
            "errors": list(self.errors),
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
            collected.extend(load_linkedin_export(linkedin))
        except Exception as exc:
            result.errors.append(f"linkedin: {exc}")

    result.claims = _dedupe(collected)
    return result

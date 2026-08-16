"""Deterministic structural parsing of a resume.

This reads the shape of the document (section headings, list items, comma
separated skills) and emits one claim per statement, each pointing at the line
it came from. It makes no judgment about whether a claim is true; that is the
reconciliation layer's job.

An LLM refinement pass can add claims this misses (see `refine.py`), but the
structural pass always runs and never depends on a network call.
"""

from __future__ import annotations

import re

from veriquill.claims.documents import Document
from veriquill.claims.models import Claim, ClaimKind, ClaimSource

_SECTION_KINDS: dict[ClaimKind, tuple[str, ...]] = {
    ClaimKind.ROLE: ("experience", "employment", "work history", "professional"),
    ClaimKind.PROJECT: ("projects", "personal projects", "selected projects"),
    ClaimKind.SKILL: ("skills", "technical skills", "technologies", "tooling"),
    ClaimKind.EDUCATION: ("education", "academics", "qualifications"),
    ClaimKind.ACHIEVEMENT: ("achievements", "awards", "publications"),
}

_BULLET = re.compile(r"^\s*[-*•·]\s*")
_PROJECT_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*[-–:]\s+(.*)$")
_MIN_STATEMENT_CHARS = 3


def _heading_kind(line: str) -> ClaimKind | None:
    """A heading is a short line that names a known section."""
    stripped = line.strip().strip(":").lower()
    if not stripped or len(stripped) > 40:
        return None
    for kind, names in _SECTION_KINDS.items():
        if stripped in names:
            return kind
    return None


def _split_skills(text: str) -> list[str]:
    parts = re.split(r"[,;|/]| and ", text)
    return [p.strip() for p in parts if p.strip()]


def parse_resume(document: Document) -> list[Claim]:
    claims: list[Claim] = []
    current: ClaimKind | None = None

    for number, raw in enumerate(document.lines, start=1):
        line = raw.strip()
        if not line:
            continue

        heading = _heading_kind(line)
        if heading is not None:
            current = heading
            continue

        if current is None:
            continue

        statement = _BULLET.sub("", line).strip()
        if len(statement) < _MIN_STATEMENT_CHARS:
            continue

        source = ClaimSource(
            document=document.name,
            locator=f"line {number}",
            excerpt=raw,
        )

        if current is ClaimKind.SKILL:
            for skill in _split_skills(statement):
                claims.append(
                    Claim(
                        kind=ClaimKind.SKILL,
                        text=skill,
                        source=source,
                        subject=skill.lower(),
                    )
                )
            continue

        subject: str | None = None
        if current is ClaimKind.PROJECT:
            match = _PROJECT_NAME.match(statement)
            if match is not None:
                subject = match.group(1).lower()

        claims.append(
            Claim(
                kind=current,
                text=statement,
                source=source,
                subject=subject,
            )
        )

    return claims

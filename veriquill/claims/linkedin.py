"""LinkedIn claims, from a user-provided export only.

Section 12 of the specification forbids scraping LinkedIn or any source that
prohibits it. That rule is enforced structurally here: this module reads local
files and refuses a URL outright. There is no HTTP client in this file, and
none should ever be added to it.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from veriquill.claims.models import Claim, ClaimKind, ClaimSource


class ScrapingRefused(RuntimeError):
    """Raised when something that looks like a URL is passed in."""


_CSV_KINDS = {
    "positions": ClaimKind.ROLE,
    "skills": ClaimKind.SKILL,
    "education": ClaimKind.EDUCATION,
    "projects": ClaimKind.PROJECT,
    "endorsement_received_info": ClaimKind.ENDORSEMENT,
}


def _refuse_urls(source: str) -> None:
    lowered = source.strip().lower()
    if lowered.startswith(("http://", "https://", "www.", "linkedin.com")):
        raise ScrapingRefused(
            "Veriquill does not fetch LinkedIn profiles. Provide the candidate's "
            "own data export (or a manual JSON entry) as a local file."
        )


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        for key, value in row.items():
            if key.strip().lower() == name and value and value.strip():
                return value.strip()
    return ""


def _claims_from_csv(path: Path) -> list[Claim]:
    kind = _CSV_KINDS.get(path.stem.strip().lower().replace(" ", "_"), ClaimKind.ROLE)
    claims: list[Claim] = []

    with path.open(encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            excerpt = ", ".join(v.strip() for v in row.values() if v and v.strip())
            if not excerpt:
                continue
            source = ClaimSource(
                document=path.name, locator=f"row {index}", excerpt=excerpt
            )

            if kind is ClaimKind.SKILL:
                name = _first(row, "name", "skill")
                if not name:
                    continue
                claims.append(
                    Claim(kind=kind, text=name, source=source, subject=name.lower())
                )
                continue

            title = _first(row, "title", "position", "school name", "degree name")
            company = _first(row, "company name", "company", "school name")
            description = _first(row, "description", "notes")
            text = " at ".join(part for part in (title, company) if part) or excerpt
            if description:
                text = f"{text}: {description}"

            claims.append(
                Claim(
                    kind=kind,
                    text=text,
                    source=source,
                    subject=(company or title or None) and (company or title).lower(),
                )
            )

    return claims


def _claims_from_json(path: Path) -> list[Claim]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    claims: list[Claim] = []

    for index, position in enumerate(payload.get("positions", []), start=1):
        title = str(position.get("title", "")).strip()
        company = str(position.get("company", "")).strip()
        description = str(position.get("description", "")).strip()
        text = " at ".join(part for part in (title, company) if part)
        if description:
            text = f"{text}: {description}" if text else description
        if not text:
            continue
        claims.append(
            Claim(
                kind=ClaimKind.ROLE,
                text=text,
                source=ClaimSource(
                    document=path.name, locator=f"positions[{index - 1}]", excerpt=text
                ),
                subject=company.lower() or None,
            )
        )

    for skill in payload.get("skills", []):
        name = str(skill).strip()
        if not name:
            continue
        claims.append(
            Claim(
                kind=ClaimKind.SKILL,
                text=name,
                source=ClaimSource(
                    document=path.name, locator=f"skills[{name}]", excerpt=name
                ),
                subject=name.lower(),
            )
        )

    for endorsement in payload.get("endorsements", []):
        skill = str(endorsement.get("skill", "")).strip()
        if not skill:
            continue
        count = endorsement.get("count", 0)
        text = f"{skill} endorsed by {count} connection(s)"
        claims.append(
            Claim(
                kind=ClaimKind.ENDORSEMENT,
                text=text,
                source=ClaimSource(
                    document=path.name, locator=f"endorsements[{skill}]", excerpt=text
                ),
                subject=skill.lower(),
                # An endorsement is a popularity signal, not evidence of skill.
                confidence=0.3,
            )
        )

    return claims


def load_linkedin_export(source: str | Path) -> list[Claim]:
    _refuse_urls(str(source))

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"LinkedIn export not found: {path}")

    if path.suffix.lower() == ".csv":
        return _claims_from_csv(path)
    if path.suffix.lower() == ".json":
        return _claims_from_json(path)

    raise ValueError(
        f"unsupported LinkedIn export {path.suffix}; provide the .csv files from "
        "the LinkedIn data export, or a .json manual entry"
    )

import json

import pytest

from veriquill.claims.linkedin import ScrapingRefused, load_linkedin_export
from veriquill.claims.models import ClaimKind


def test_positions_csv_becomes_role_claims(tmp_path):
    path = tmp_path / "Positions.csv"
    path.write_text(
        "Company Name,Title,Description,Started On,Finished On\n"
        "Acme Corp,Senior Engineer,Led the auth redesign,Jan 2022,Mar 2024\n",
        encoding="utf-8",
    )

    claims = load_linkedin_export(path)

    roles = [c for c in claims if c.kind is ClaimKind.ROLE]
    assert roles
    assert "Senior Engineer" in roles[0].text
    assert roles[0].source.document == "Positions.csv"
    assert roles[0].source.locator == "row 1"


def test_skills_csv_becomes_skill_claims(tmp_path):
    path = tmp_path / "Skills.csv"
    path.write_text("Name\nPython\nKubernetes\n", encoding="utf-8")

    subjects = {c.subject for c in load_linkedin_export(path)}

    assert {"python", "kubernetes"} <= subjects


def test_manual_json_entry_is_accepted(tmp_path):
    path = tmp_path / "linkedin.json"
    path.write_text(
        json.dumps(
            {
                "positions": [
                    {"title": "Staff Engineer", "company": "Globex", "description": "Owned billing"}
                ],
                "skills": ["Go", "Terraform"],
                "endorsements": [{"skill": "Go", "count": 12}],
            }
        ),
        encoding="utf-8",
    )

    claims = load_linkedin_export(path)
    kinds = {c.kind for c in claims}

    assert ClaimKind.ROLE in kinds
    assert ClaimKind.SKILL in kinds
    assert ClaimKind.ENDORSEMENT in kinds


def test_a_url_is_refused_rather_than_fetched():
    """Section 12: never scrape LinkedIn or any source that prohibits it.

    Refusing at the input boundary makes the rule structural rather than a
    matter of remembering not to write a fetch call.
    """
    with pytest.raises(ScrapingRefused, match="export"):
        load_linkedin_export("https://www.linkedin.com/in/someone/")


def test_every_claim_quotes_its_row(tmp_path):
    path = tmp_path / "Positions.csv"
    path.write_text(
        "Company Name,Title,Description\nAcme,Engineer,Built things\n", encoding="utf-8"
    )

    for claim in load_linkedin_export(path):
        assert claim.source.excerpt.strip()
        assert claim.source.locator.strip()


def test_empty_export_yields_no_claims(tmp_path):
    path = tmp_path / "Skills.csv"
    path.write_text("Name\n", encoding="utf-8")
    assert load_linkedin_export(path) == []

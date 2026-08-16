import json

from veriquill.claims.engine import collect_claims
from veriquill.claims.models import ClaimKind
from veriquill.config import Settings

RESUME_TEXT = """EXPERIENCE
Senior Engineer, Acme Corp (2022 - 2024)
Led the auth redesign across three services.

SKILLS
Python, Kubernetes
"""


def _settings(tmp_path) -> Settings:
    return Settings(github_token="t", data_dir=tmp_path / "data")


def _resume(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text(RESUME_TEXT, encoding="utf-8")
    return path


def test_resume_only_collection(tmp_path):
    result = collect_claims(_settings(tmp_path), resume=_resume(tmp_path))

    assert result.claims
    assert {c.source.document for c in result.claims} == {"resume.txt"}
    assert result.errors == []


def test_resume_and_linkedin_are_merged(tmp_path):
    linkedin = tmp_path / "linkedin.json"
    linkedin.write_text(
        json.dumps({"skills": ["Go"], "positions": [{"title": "Staff Engineer"}]}),
        encoding="utf-8",
    )

    result = collect_claims(
        _settings(tmp_path), resume=_resume(tmp_path), linkedin=linkedin
    )

    documents = {c.source.document for c in result.claims}
    assert documents == {"resume.txt", "linkedin.json"}


def test_a_skill_claimed_in_both_places_is_recorded_once(tmp_path):
    linkedin = tmp_path / "linkedin.json"
    linkedin.write_text(json.dumps({"skills": ["Python"]}), encoding="utf-8")

    result = collect_claims(
        _settings(tmp_path), resume=_resume(tmp_path), linkedin=linkedin
    )

    python_claims = [
        c
        for c in result.claims
        if c.kind is ClaimKind.SKILL and c.subject == "python"
    ]
    assert len(python_claims) == 1
    # The resume is the richer source, so it wins the de-duplication.
    assert python_claims[0].source.document == "resume.txt"


def test_an_unreadable_source_is_recorded_as_an_error_not_a_crash(tmp_path):
    result = collect_claims(_settings(tmp_path), resume=tmp_path / "missing.txt")

    assert result.claims == []
    assert result.errors
    assert "missing.txt" in result.errors[0]


def test_a_linkedin_url_is_refused_and_recorded(tmp_path):
    result = collect_claims(
        _settings(tmp_path),
        resume=_resume(tmp_path),
        linkedin="https://www.linkedin.com/in/someone/",
    )

    assert result.claims  # the resume still parsed
    assert any("export" in e for e in result.errors)


def test_summary_is_serialisable_and_keeps_provenance(tmp_path):
    result = collect_claims(_settings(tmp_path), resume=_resume(tmp_path))
    payload = result.to_dict()

    assert payload["claim_count"] == len(result.claims)
    assert all(c["source"]["locator"] for c in payload["claims"])
    assert all(c["source"]["excerpt"] for c in payload["claims"])


def test_no_sources_at_all_is_not_an_error(tmp_path):
    result = collect_claims(_settings(tmp_path))
    assert result.claims == []
    assert result.errors == []

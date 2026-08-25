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


def test_the_same_sentence_classified_twice_is_kept_once(tmp_path):
    """A refiner may label one line both a role and an achievement.

    It is still one statement, and raising it twice in the dossier means the
    recruiter asks the same question twice.
    """
    from veriquill.claims.engine import _dedupe
    from veriquill.claims.models import Claim, ClaimKind, ClaimSource

    source = ClaimSource(
        document="resume.txt", locator="line 5", excerpt="Built the payments service"
    )
    claims = [
        Claim(kind=ClaimKind.ROLE, text="Built the payments service", source=source),
        Claim(
            kind=ClaimKind.ACHIEVEMENT, text="Built the payments service", source=source
        ),
    ]

    assert len(_dedupe(claims)) == 1


def test_different_statements_from_one_line_are_both_kept(tmp_path):
    from veriquill.claims.engine import _dedupe
    from veriquill.claims.models import Claim, ClaimKind, ClaimSource

    source = ClaimSource(
        document="resume.txt", locator="line 5", excerpt="Built the payments service"
    )
    claims = [
        Claim(kind=ClaimKind.ROLE, text="Built the payments service", source=source),
        Claim(
            kind=ClaimKind.SKILL, text="payments", source=source, subject="payments"
        ),
    ]

    assert len(_dedupe(claims)) == 2


def test_sensitive_fields_are_redacted_before_any_claim_is_built(tmp_path):
    """A protected attribute must not survive into claims, models, or logs."""
    resume = tmp_path / "cv.txt"
    resume.write_text(
        "\n".join(
            [
                "Alice Example",
                "Date of Birth: 14 March 1998",
                "Gender: Female",
                "",
                "SKILLS",
                "Python, PostgreSQL",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_claims(_settings(tmp_path), resume=resume)

    blob = json.dumps(result.to_dict())
    assert "1998" not in blob
    assert "Female" not in blob
    assert result.redactions
    assert {r["category"] for r in result.redactions} == {"date_of_birth", "gender"}


def test_a_redaction_record_never_repeats_the_value_it_removed(tmp_path):
    resume = tmp_path / "cv.txt"
    resume.write_text("Religion: Hindu\n\nSKILLS\nGo\n", encoding="utf-8")

    result = collect_claims(_settings(tmp_path), resume=resume)

    assert result.redactions
    assert "Hindu" not in json.dumps(result.redactions)
    assert result.redactions[0]["line"] == 1


def test_a_clean_resume_records_no_redactions(tmp_path):
    resume = tmp_path / "cv.txt"
    resume.write_text("SKILLS\nPython, Kubernetes\n", encoding="utf-8")

    result = collect_claims(_settings(tmp_path), resume=resume)

    assert result.redactions == []


# --- redaction covers both document paths, not just the resume -------------


_PROTECTED_VALUES = ("indian", "1996", "14 march", "married", "hindu")


def _values_surviving(claims) -> list[str]:
    """The values themselves. Labels are kept deliberately, so they are not leaks."""
    found: list[str] = []
    for claim in claims:
        blob = f"{claim.text} {claim.source.excerpt}".lower()
        found += [value for value in _PROTECTED_VALUES if value in blob]
    return found


def _linkedin_export(tmp_path):
    """A positions export whose free-text summary states protected attributes.

    LinkedIn's own export carries a Birth Date column, and a position summary
    is free text in which people write these outright.
    """
    path = tmp_path / "Positions.csv"
    path.write_text(
        "Company Name,Title,Description,Started On,Finished On\n"
        'Acme,Engineer,"Nationality: Indian. Date of Birth: 14 March 1996. '
        'Built the billing service.",Jan 2020,Dec 2022\n',
        encoding="utf-8",
    )
    return path


def test_a_linkedin_export_is_redacted_like_a_resume(tmp_path):
    """The resume path redacted and this one did not, so the claim, its quoted
    excerpt, the stored dossier and the reviewer's screen all carried whatever
    the export held."""
    settings = Settings(
        github_token="t", data_dir=tmp_path / "data", claim_refinement_enabled=False
    )

    result = collect_claims(settings, linkedin=_linkedin_export(tmp_path))

    assert result.claims
    assert _values_surviving(result.claims) == []


def test_the_linkedin_redaction_is_recorded_like_the_resume_one(tmp_path):
    """The dossier says a field was present and removed, never what it held."""
    settings = Settings(
        github_token="t", data_dir=tmp_path / "data", claim_refinement_enabled=False
    )

    result = collect_claims(settings, linkedin=_linkedin_export(tmp_path))

    categories = {row["category"] for row in result.redactions}
    assert {"nationality", "date_of_birth"} <= categories
    assert all(row["document"] == "linkedin" for row in result.redactions)
    assert not any(
        value in row["note"].lower() for row in result.redactions for value in _PROTECTED_VALUES
    )


def test_the_rest_of_a_linkedin_claim_survives_redaction(tmp_path):
    """Redaction must not eat the claim it was cleaning."""
    settings = Settings(
        github_token="t", data_dir=tmp_path / "data", claim_refinement_enabled=False
    )

    result = collect_claims(settings, linkedin=_linkedin_export(tmp_path))

    assert any("billing service" in claim.source.excerpt.lower() for claim in result.claims)


def test_an_export_with_nothing_protected_is_left_alone(tmp_path):
    settings = Settings(
        github_token="t", data_dir=tmp_path / "data", claim_refinement_enabled=False
    )
    path = tmp_path / "Positions.csv"
    path.write_text(
        "Company Name,Title,Description,Started On,Finished On\n"
        "Acme,Engineer,Built the billing service.,Jan 2020,Dec 2022\n",
        encoding="utf-8",
    )

    result = collect_claims(settings, linkedin=path)

    assert result.redactions == []
    assert any("billing service" in claim.source.excerpt.lower() for claim in result.claims)

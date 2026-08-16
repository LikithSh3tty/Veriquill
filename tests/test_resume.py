from veriquill.claims.documents import Document
from veriquill.claims.models import ClaimKind
from veriquill.claims.resume import parse_resume

RESUME = Document(
    name="resume.txt",
    lines=(
        "Jane Candidate",
        "jane@example.com",
        "",
        "EXPERIENCE",
        "Senior Engineer, Acme Corp (2022 - 2024)",
        "Led the auth redesign across three services.",
        "",
        "PROJECTS",
        "veriquill - built a RAG pipeline with retrieval and evaluation",
        "",
        "SKILLS",
        "Python, PostgreSQL, Docker, Kubernetes",
        "",
        "EDUCATION",
        "M.Sc. Artificial Intelligence, CHRIST University, 2026",
    ),
)


def test_section_headings_are_detected():
    claims = parse_resume(RESUME)
    kinds = {c.kind for c in claims}
    assert ClaimKind.ROLE in kinds
    assert ClaimKind.SKILL in kinds
    assert ClaimKind.PROJECT in kinds
    assert ClaimKind.EDUCATION in kinds


def test_every_claim_records_the_line_it_came_from():
    for claim in parse_resume(RESUME):
        assert claim.source.document == "resume.txt"
        assert claim.source.locator.startswith("line ")
        assert claim.source.excerpt.strip()


def test_skills_are_split_into_individual_claims():
    skills = {c.subject for c in parse_resume(RESUME) if c.kind is ClaimKind.SKILL}
    assert {"python", "postgresql", "docker", "kubernetes"} <= skills


def test_a_role_claim_keeps_its_full_sentence():
    roles = [c for c in parse_resume(RESUME) if c.kind is ClaimKind.ROLE]
    assert any("auth redesign" in c.text.lower() for c in roles)


def test_project_claim_subject_is_the_project_name():
    projects = [c for c in parse_resume(RESUME) if c.kind is ClaimKind.PROJECT]
    assert any(c.subject == "veriquill" for c in projects)


def test_the_locator_points_at_the_real_line():
    claim = next(c for c in parse_resume(RESUME) if "auth redesign" in c.text.lower())
    line_number = int(claim.source.locator.removeprefix("line "))
    assert RESUME.lines[line_number - 1] == claim.source.excerpt


def test_a_document_with_no_recognisable_sections_yields_no_claims():
    empty = Document(name="blank.txt", lines=("", "   ", ""))
    assert parse_resume(empty) == []


def test_headings_themselves_are_not_emitted_as_claims():
    texts = {c.text.strip().upper() for c in parse_resume(RESUME)}
    assert "EXPERIENCE" not in texts
    assert "SKILLS" not in texts

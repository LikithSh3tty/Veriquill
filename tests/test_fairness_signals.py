"""Protected-attribute content must never reach a score, a model, or a log."""

from __future__ import annotations

import pytest

from veriquill.claims.documents import Document
from veriquill.fairness.signals import (
    CATEGORIES,
    redact_document,
    redact_text,
    scan_lines,
)


def test_every_category_has_at_least_one_pattern():
    assert CATEGORIES
    for name, patterns in CATEGORIES.items():
        assert patterns, f"{name} has no patterns"


@pytest.mark.parametrize(
    ("line", "category"),
    [
        ("Date of Birth: 14 March 1998", "date_of_birth"),
        ("DOB : 1998-03-14", "date_of_birth"),
        ("Age: 27", "age"),
        ("27 years old", "age"),
        ("Gender: Female", "gender"),
        ("Sex - Male", "gender"),
        ("Marital Status: Married", "marital_status"),
        ("Nationality: Indian", "nationality"),
        ("Citizenship: German", "nationality"),
        ("Religion: Hindu", "religion"),
        ("Caste: General", "religion"),
        ("Blood Group: O+", "health"),
        ("Disability: none", "health"),
        ("Photograph attached", "photo"),
    ],
)
def test_each_sensitive_field_is_detected(line, category):
    matches = scan_lines([line])

    assert [m.category for m in matches] == [category]
    assert matches[0].line == 1


def test_technical_resume_text_is_left_alone():
    lines = [
        "Senior Backend Engineer, payments platform",
        "Python, PostgreSQL, single-page apps, Kubernetes",
        "Reduced p99 latency by 40% over 18 months",
        "Led a team of 6 engineers; sole author of the billing service",
        "Born-again REST evangelist",
    ]

    assert scan_lines(lines) == []


def test_redaction_keeps_the_label_and_removes_the_value():
    redacted = redact_text("Date of Birth: 14 March 1998")

    assert "1998" not in redacted
    assert "Date of Birth" in redacted
    assert "redacted" in redacted


def test_redaction_preserves_line_count_and_numbering():
    document = Document(
        name="cv.txt",
        lines=("Alice Example", "Gender: Female", "", "Python, Go"),
    )

    cleaned, matches = redact_document(document)

    assert len(cleaned.lines) == len(document.lines)
    assert cleaned.lines[0] == "Alice Example"
    assert cleaned.lines[3] == "Python, Go"
    assert cleaned.lines[2] == ""
    assert [m.line for m in matches] == [2]


def test_a_redacted_document_no_longer_scans_dirty():
    document = Document(
        name="cv.txt",
        lines=("Nationality: Indian", "Age: 27", "Backend engineer"),
    )

    cleaned, _ = redact_document(document)

    assert scan_lines(cleaned.lines) == []


def test_a_match_never_carries_the_sensitive_value():
    matches = scan_lines(["Religion: Hindu"])

    assert "Hindu" not in matches[0].describe()
    assert "religion" in matches[0].describe()
    assert matches[0].describe().startswith("resume line 1")


def test_several_categories_on_one_line_are_all_redacted():
    redacted = redact_text("Gender: Female | Marital Status: Single")

    assert "Female" not in redacted
    assert "Single" not in redacted


def test_scanning_is_case_insensitive():
    assert scan_lines(["gender: female"])
    assert scan_lines(["GENDER: FEMALE"])

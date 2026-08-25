"""Keeping protected attributes out of the pipeline (specification §12).

Veriquill must never infer or use a protected attribute. Not inferring one is
not enough on its own: resumes in many countries routinely state date of birth,
marital status, nationality, religion, and photographs outright, so the data
arrives whether or not the tool asks for it. Once it is in the text it can reach
a language model, a log, or a recruiter's screen, and at that point "we never
used it" is a claim nobody can check.

So the text is redacted at the door: before parsing, before any model sees it,
before anything is stored. Redaction keeps the field's label and removes its
value, so the dossier can say honestly that a field was present and was dropped.
That is more auditable than deleting the line and leaving no trace.

Patterns are deliberately anchored to labelled fields. Bare words like "single"
or "male" appear in ordinary technical prose, and redacting those would mangle a
resume while protecting nobody.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Label separators: colon, hyphen, en dash, em dash.
_LABEL = "[ \t]*[:\\-–—][ \t]*"

# A redacted line must not match again. A second pass would redact the marker
# itself, and no scan could then confirm the text came out clean.
_VALUE = "(?!\\[redacted)\\S.*"

CATEGORIES: dict[str, tuple[re.Pattern[str], ...]] = {
    "date_of_birth": (
        re.compile(
            r"\b(date\s+of\s+birth|d\.?o\.?b\.?|birth\s*date)" + _LABEL + _VALUE,
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(born)\s+(?:on\s+)?\d{1,2}[\s/.-]+\w+[\s/.-]+\d{2,4}", re.IGNORECASE
        ),
    ),
    "age": (
        re.compile(r"\b(age)" + _LABEL + r"\d{1,3}\b", re.IGNORECASE),
        re.compile(r"\b\d{1,3}\s+years?\s+old\b", re.IGNORECASE),
    ),
    "gender": (re.compile(r"\b(gender|sex|pronouns)" + _LABEL + _VALUE, re.IGNORECASE),),
    "marital_status": (
        re.compile(
            r"\b(marital\s+status|civil\s+status|spouse)" + _LABEL + _VALUE, re.IGNORECASE
        ),
    ),
    "nationality": (
        re.compile(
            r"\b(nationality|citizenship|country\s+of\s+birth|place\s+of\s+birth)"
            + _LABEL
            + _VALUE,
            re.IGNORECASE,
        ),
    ),
    "religion": (
        re.compile(r"\b(religion|caste|community|faith)" + _LABEL + _VALUE, re.IGNORECASE),
    ),
    "health": (
        re.compile(
            r"\b(blood\s+group|disability|medical\s+condition|health\s+status)"
            + _LABEL
            + _VALUE,
            re.IGNORECASE,
        ),
    ),
    "photo": (
        re.compile(
            r"\b(photograph|passport\s+size\s+photo)(?!\s*:?\s*\[redacted).*",
            re.IGNORECASE,
        ),
        re.compile(r"\b(photo)" + _LABEL + _VALUE, re.IGNORECASE),
    ),
}


@dataclass(frozen=True, slots=True)
class SensitiveMatch:
    """A protected-attribute field that was found and removed.

    It carries the category and the location, never the value. A record of a
    redaction that quoted what it redacted would defeat the point of redacting.
    """

    category: str
    line: int
    document: str = "resume"

    def describe(self) -> str:
        return (
            f"{self.document} line {self.line}: a {self.category.replace('_', ' ')} "
            "field was present and was removed before any analysis"
        )


def scan_lines(
    lines: Sequence[str] | Iterable[str], document: str = "resume"
) -> list[SensitiveMatch]:
    """Find every labelled protected-attribute field, in line order."""
    matches: list[SensitiveMatch] = []

    for number, line in enumerate(lines, start=1):
        for category, patterns in CATEGORIES.items():
            if any(pattern.search(line) for pattern in patterns):
                matches.append(
                    SensitiveMatch(category=category, line=number, document=document)
                )

    return matches


def _replacement(match: re.Match[str], category: str) -> str:
    """Keep the field's own label so the redaction is visible, drop the value."""
    label = match.group(1) if match.re.groups else category
    return f"{label}: [redacted: {category}]"


def redact_text(text: str) -> str:
    """Remove the value of every protected-attribute field, keeping the label."""
    cleaned = text

    for category, patterns in CATEGORIES.items():
        for pattern in patterns:
            cleaned = pattern.sub(
                lambda match, category=category: _replacement(match, category), cleaned
            )

    return cleaned


#: Sentence boundary, keeping the terminator with the sentence it ends.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def redact_prose(text: str) -> str:
    """Redact free text, one sentence at a time.

    A labelled field runs to the end of its line, which is right for a resume
    where each field has a line of its own. Prose puts several sentences on
    one line, so the same rule ate whatever followed: a summary reading
    'Date of Birth: 14 March 1996. Built the billing service.' lost the claim
    along with the date. Sentences are redacted separately, so a protected
    value takes only its own sentence with it.
    """
    parts = _SENTENCE.split(text)
    if len(parts) == 1:
        return redact_text(text)

    # Rebuilt with the original separators, so spacing survives.
    separators = _SENTENCE.findall(text)
    cleaned = [redact_text(part) for part in parts]
    out = cleaned[0]
    for separator, part in zip(separators, cleaned[1:], strict=False):
        out += separator + part
    return out

def redact_document(document):
    """Redact a document's sensitive values, preserving every line number.

    Line numbers are load-bearing: a claim quotes "resume line 12" and the
    reconciliation layer matches that quote back to the document. Redaction
    therefore rewrites lines and never removes them.
    """
    from veriquill.claims.documents import Document

    matches = scan_lines(document.lines, document.name)
    cleaned = tuple(redact_text(line) for line in document.lines)

    return Document(name=document.name, lines=cleaned), matches

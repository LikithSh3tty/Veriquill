"""The compliance pack (specification §11).

Recruitment AI is high-risk under the EU AI Act, and an automated employment
decision tool under NYC Local Law 144 owes candidates notice of what it does.
This module builds that notice.

It is generated from the running code rather than written by hand. A hand-kept
document describes the tool someone remembered; this one describes the tool that
is installed. The excluded-attribute list comes from the scanner itself and the
measured dimensions come from the rubric, so a change to either shows up in the
disclosure without anybody remembering to update prose.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from veriquill import __version__
from veriquill.fairness.signals import CATEGORIES
from veriquill.rubric import DEFAULT_WEIGHTS, DIMENSIONS

# What each dimension actually reads. Keyed by dimension so a new dimension
# without an entry is visible immediately rather than quietly undocumented.
DIMENSION_EVIDENCE: dict[str, str] = {
    "authenticity": (
        "commit history read from a full clone: cadence, first-commit share, "
        "fork origin, and whether the candidate authored the commits"
    ),
    "code_quality": (
        "static analysis of authored Python: cyclomatic complexity, lint "
        "compliance, and modules nothing imports"
    ),
    "claim_corroboration": (
        "claims taken from the candidate's own documents, reconciled against "
        "repository evidence"
    ),
    "test_quality": (
        "presence of tests and whether their assertions are meaningful, rather "
        "than how many tests exist"
    ),
    "security": "security-hygiene findings from static analysis of authored code",
    "breadth": "how many repositories hold code the candidate actually authored",
}

HUMAN_OVERSIGHT: tuple[str, ...] = (
    "A ranked comparison is created pending review and cannot be exported until "
    "a named human approves it.",
    "An approval covers exactly the revision it saw. Any later review action "
    "reopens the gate and requires a fresh approval.",
    "A reviewer can dismiss any individual flag or override a verdict band, and "
    "must give a reason for each; the machine result is never edited.",
    "Every review action is appended to an audit log that is never updated or "
    "deleted, so replaying it reconstructs any state the comparison has held.",
)

HARD_LIMITS: tuple[str, ...] = (
    "Veriquill never auto-rejects and never auto-hires. It supports a decision "
    "and does not make one.",
    "Veriquill never infers or uses a protected attribute. Where a document "
    "states one outright, the value is removed before parsing.",
    "Veriquill never scrapes LinkedIn or any source that prohibits it. LinkedIn "
    "data is read only from a candidate-provided export.",
    "A red flag is never treated as proof of wrongdoing. Innocent explanations "
    "exist for every check.",
    "No score is presented without its evidence, its coverage, and its "
    "confidence band.",
)

DATA_HANDLING: tuple[str, ...] = (
    "Sources: public GitHub repositories, a candidate-supplied resume, and a "
    "candidate-supplied LinkedIn export. Nothing else is collected.",
    "Clones are ephemeral and deleted after analysis; findings, dossiers, and "
    "review actions persist in a local SQLite database.",
    "Protected-attribute fields are removed at ingestion, so they are never "
    "stored, never logged, and never sent to a language model.",
    "The only optional model call rephrases claims already present in the "
    "candidate's own document, and a claim it cannot quote back is discarded.",
)


def build_disclosure(audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the disclosure pack from the code that is actually running."""
    notes: list[str] = [
        "This pack is generated from the installed code, not maintained by hand.",
        "It is a self-disclosure. Jurisdictions such as New York City require an "
        "independent bias audit, which this does not replace.",
    ]

    if audit is None:
        notes.append(
            "No bias audit was supplied with this pack, so no selection-rate "
            "result is reported. Absence of a result is not a pass."
        )

    return {
        "tool": "Veriquill",
        "tool_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Veriquill verifies whether a portfolio is the candidate's own "
            "iterative work and evaluates the code in it, then ranks candidates "
            "against a recruiter-supplied rubric for a human to review."
        ),
        "what_is_measured": [
            {
                "dimension": dimension,
                "default_weight": DEFAULT_WEIGHTS[dimension],
                "evidence": DIMENSION_EVIDENCE.get(dimension, ""),
            }
            for dimension in DIMENSIONS
        ],
        "what_is_excluded": [
            {
                "category": category,
                "handling": (
                    "detected by labelled field and removed before parsing, "
                    "before any model call, and before storage"
                ),
            }
            for category in sorted(CATEGORIES)
        ],
        "human_oversight": list(HUMAN_OVERSIGHT),
        "hard_limits": list(HARD_LIMITS),
        "data_handling": list(DATA_HANDLING),
        "bias_audit": audit,
        "notes": notes,
    }


def render_markdown(disclosure: dict[str, Any]) -> str:
    """Render the pack as the document a candidate or regulator would read."""
    lines: list[str] = [
        f"# {disclosure['tool']} disclosure pack",
        "",
        f"Version {disclosure['tool_version']} · generated {disclosure['generated_at']}",
        "",
        disclosure["purpose"],
        "",
        "## What is measured",
        "",
        "| Dimension | Default weight | Evidence it reads |",
        "| --- | --- | --- |",
    ]

    for row in disclosure["what_is_measured"]:
        lines.append(
            f"| {row['dimension']} | {row['default_weight']:.2f} | {row['evidence']} |"
        )

    lines += ["", "## What is excluded", ""]
    for row in disclosure["what_is_excluded"]:
        lines.append(f"- **{row['category']}** — {row['handling']}")

    lines += ["", "## Human oversight", ""]
    lines += [f"- {item}" for item in disclosure["human_oversight"]]

    lines += ["", "## Hard limits", ""]
    lines += [f"- {item}" for item in disclosure["hard_limits"]]

    lines += ["", "## Data handling", ""]
    lines += [f"- {item}" for item in disclosure["data_handling"]]

    lines += ["", "## Bias audit", ""]
    audit = disclosure.get("bias_audit")
    if audit is None:
        lines.append("No bias audit was supplied with this pack.")
    else:
        ratio = audit.get("impact_ratio")
        passes = audit.get("passes_four_fifths")
        lines.append(
            f"- Impact ratio: {ratio if ratio is not None else 'not computable'}"
        )
        lines.append(f"- Passes the four-fifths rule: {passes}")
        for note in audit.get("notes", []):
            lines.append(f"- {note}")

    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in disclosure["notes"]]

    return "\n".join(lines) + "\n"

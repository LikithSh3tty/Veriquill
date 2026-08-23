"""Reading code as text, for languages no parser here understands.

Python gets a real syntax tree. Every other language Veriquill analyses in depth
is read lexically, because the alternative is running the candidate's own
toolchain and this tool clones repositories it has every reason to treat as
untrusted.

The pieces that are genuinely language independent live here: blanking spans
while preserving offsets, matching a brace to its partner, and turning an offset
into the line number a reader will see. What differs between languages is which
spans count as comments and literals, and that stays with the language.

Everything here preserves offsets rather than deleting text. A finding cites a
file and a line, and a line number computed against a shortened copy of the file
points at the wrong line, which is worse than no citation at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from veriquill.findings import EvidenceRef, Finding, Severity


def blank(match: re.Match[str]) -> str:
    """Replace a matched span with spaces, keeping its newlines."""
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_spans(source: str, pattern: re.Pattern[str]) -> str:
    """Blank every span the pattern matches, leaving the file the same length."""
    return pattern.sub(blank, source)


def body_end(source: str, open_brace: int, opener: str = "{", closer: str = "}") -> int:
    """Index just past the brace closing the one at `open_brace`.

    Callers pass source that has already had literals blanked, so a brace inside
    a string cannot move where a body appears to end.
    """
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(source)


def line_of(source: str, offset: int) -> int:
    """The 1-based line an offset falls on."""
    return source.count("\n", 0, offset) + 1


def alternation(terms: object, *, boundary: bool = True) -> str:
    """One regex alternative per term, longest first.

    Longest first because Python's `re` takes the first alternative that matches
    at a position rather than the longest, so ordering is what turns leftmost
    into leftmost-longest.
    """
    escaped = "|".join(
        re.escape(term) for term in sorted(terms, key=lambda t: (-len(str(t)), str(t)))  # type: ignore[union-attr]
    )
    return rf"(?<!\w)(?:{escaped})(?!\w)" if boundary else f"(?:{escaped})"


@dataclass(frozen=True, slots=True)
class SecurityPattern:
    """One thing worth naming, and the sentence that explains why."""

    name: str
    pattern: re.Pattern[str]
    severity: Severity
    explanation: str


@dataclass(frozen=True, slots=True)
class Unit:
    """One function-shaped thing and how many ways it branches."""

    name: str
    line: int
    complexity: int


def read_source(
    path: Path, noise: re.Pattern[str], comments: re.Pattern[str], *, keep_literals: bool = False
) -> str | None:
    """A file with its comments blanked, and its literals blanked or kept.

    Counting code wants literals gone, so a keyword inside a message is not a
    branch and a brace inside a string does not move where a body ends. Reading
    what code says wants them kept, because a hardcoded credential and an
    interpolated command live inside them. Comments go either way: prose about a
    password is not a password.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return strip_spans(source, comments if keep_literals else noise)


def complexity_finding(
    repo: str,
    root: Path,
    offenders: list[tuple[Path, Unit]],
    *,
    language: str,
    unit: str,
    threshold: int,
    confidence: float,
) -> list[Finding]:
    """The same finding for every language read this way.

    Only the wording differs, and it differs in ways a reader would notice: Java
    has methods where Go has functions. Everything else - the ordering, the cap
    at five, the severity step, the admission that the count is approximate - is
    one decision made once.
    """
    if not offenders:
        return []

    offenders = sorted(offenders, key=lambda item: item[1].complexity, reverse=True)
    worst = offenders[:5]
    highest = worst[0][1]

    return [
        Finding(
            check_id="codeeval.high_complexity",
            severity=Severity.MEDIUM if highest.complexity < 30 else Severity.HIGH,
            title=f"{unit.capitalize()}s with high cyclomatic complexity",
            rationale=(
                f"{len(offenders)} {language} {unit}(s) reach a branch count of "
                f"{threshold} or more. The highest is {highest.name} at "
                f"{highest.complexity}. Counted from decision keywords rather than a "
                "parsed syntax tree, so treat it as close rather than exact."
            ),
            confidence=confidence,
            evidence=tuple(
                EvidenceRef(
                    repo=repo,
                    path=path.relative_to(root).as_posix(),
                    line=span.line,
                    detail=f"{span.name} branches {span.complexity} ways (lexical count)",
                )
                for path, span in worst
            ),
        )
    ]


def no_tests_finding(
    repo: str,
    root: Path,
    source_files: list[Path],
    *,
    language: str,
    looked_for: str,
    confidence: float,
) -> list[Finding]:
    """Source with nothing that could demonstrate it works."""
    if not source_files:
        return []

    return [
        Finding(
            check_id="codeeval.no_tests",
            severity=Severity.MEDIUM,
            title="No tests found",
            rationale=(
                f"{len(source_files)} {language} source file(s) and no test files. "
                "Untested code is not necessarily incorrect, but nothing here "
                "demonstrates that it works."
            ),
            confidence=confidence,
            evidence=(
                EvidenceRef(
                    repo=repo,
                    path=source_files[0].relative_to(root).as_posix(),
                    detail=f"no {looked_for} in the repository",
                ),
            ),
        )
    ]


def security_findings(
    repo: str,
    root: Path,
    files: list[Path],
    patterns: tuple[SecurityPattern, ...],
    *,
    language: str,
    noise: re.Pattern[str],
    comments: re.Pattern[str],
    confidence: float,
) -> list[Finding]:
    """Every security-hygiene pattern, over source that kept its literals.

    Each pattern is chosen by its language module for a low false-positive rate,
    because a false accusation costs a candidate more than a missed flag costs a
    recruiter. What is shared is the shape of the report, including the sentence
    telling the reader to confirm the context.
    """
    findings: list[Finding] = []

    for spec in patterns:
        hits: list[tuple[Path, int, str]] = []
        for path in files:
            source = read_source(path, noise, comments, keep_literals=True)
            if source is None:
                continue
            for match in spec.pattern.finditer(source):
                hits.append((path, line_of(source, match.start()), match.group(0).strip()))

        if not hits:
            continue

        findings.append(
            Finding(
                check_id=f"codeeval.security.{spec.name}",
                severity=spec.severity,
                title=f"Security hygiene: {spec.name.replace('_', ' ')}",
                rationale=(
                    f"{len(hits)} occurrence(s) in {language}: {spec.explanation}. Found "
                    "by reading the source as text, so confirm the context before "
                    "treating it as settled."
                ),
                confidence=confidence,
                evidence=tuple(
                    EvidenceRef(
                        repo=repo,
                        path=path.relative_to(root).as_posix(),
                        line=line,
                        detail=" ".join(snippet.split())[:120],
                    )
                    for path, line, snippet in hits[:5]
                ),
            )
        )

    return findings

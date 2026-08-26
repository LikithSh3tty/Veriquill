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
from collections.abc import Callable
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


#: Below this share of a repository's detected source files, a language is
#: incidental to it and an absence of tests in that language says nothing
#: about the repository. bradfitz/go-redox is 11,277 Go files, nine
#: JavaScript and two Python, and earned a finding for having no Python
#: tests. mitsuhiko/insta is 56 Rust files carrying a large test suite and
#: eight TypeScript, and earned one for having no TypeScript tests. Neither
#: sentence is false and neither is about the repository it names.
#:
#: A fifth keeps the cases that are real: bradfitz/koffer is 15 Java files
#: and 11 JavaScript, and both halves genuinely have no tests.
INCIDENTAL_SHARE = 0.2


def is_incidental(source_files: list[Path], repository_files: int) -> bool:
    """Whether this language is a footnote to the repository rather than its substance.

    Absence is the only claim this guards. A security or complexity finding
    in two files is still a finding about those two files; `no tests` is a
    statement about the repository, and a repository is not untested because
    a helper script written in another language has no suite of its own.
    """
    if not repository_files or not source_files:
        return True
    return len(source_files) / repository_files < INCIDENTAL_SHARE

def no_tests_finding(
    repo: str,
    root: Path,
    source_files: list[Path],
    *,
    language: str,
    looked_for: str,
    confidence: float,
    repository_files: int,
) -> list[Finding]:
    """Source with nothing that could demonstrate it works.

    Silent when the language is incidental to the repository, because the
    finding would be true of the files and false about the codebase.
    """
    if not source_files or is_incidental(source_files, repository_files):
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


#: One step less severe, for a finding that only ever appears in test code.
#: LOW does not fall to INFO, because INFO carries no weight at all and the
#: point is to soften the claim rather than to withdraw it.
_SOFTENED: dict[Severity, Severity] = {
    Severity.CRITICAL: Severity.HIGH,
    Severity.HIGH: Severity.MEDIUM,
    Severity.MEDIUM: Severity.LOW,
    Severity.LOW: Severity.LOW,
    Severity.INFO: Severity.INFO,
}


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
    is_test: Callable[[Path], bool] = lambda _path: False,
) -> list[Finding]:
    """Every security-hygiene pattern, over source that kept its literals.

    Each pattern is chosen by its language module for a low false-positive rate,
    because a false accusation costs a candidate more than a missed flag costs a
    recruiter. What is shared is the shape of the report, including the sentence
    telling the reader to confirm the context.

    Files are the outer loop and patterns the inner one, so each file is read
    from disk and stripped once rather than once per pattern. With five patterns
    that was five times the work for the same answer.
    """
    hits_by_pattern: dict[str, list[tuple[Path, int, str]]] = {spec.name: [] for spec in patterns}

    for path in files:
        source = read_source(path, noise, comments, keep_literals=True)
        if source is None:
            continue
        for spec in patterns:
            for match in spec.pattern.finditer(source):
                hits_by_pattern[spec.name].append(
                    (path, line_of(source, match.start()), match.group(0).strip())
                )

    findings: list[Finding] = []
    for spec in patterns:
        hits = hits_by_pattern[spec.name]
        if not hits:
            continue

        # A credential in a fixture is almost always a fixture, and an eval in a
        # test harness is not the same claim as one in a request handler. When
        # every occurrence is in test code the finding still stands and still
        # cites its lines, but it stops carrying the severity of a production
        # defect. Mixed hits keep full severity, because some of them are real.
        only_tests = all(is_test(path) for path, _line, _snippet in hits)
        severity = _SOFTENED[spec.severity] if only_tests else spec.severity
        aside = (
            " Every occurrence is in test code, so this is reported one step below "
            "its usual severity."
            if only_tests
            else ""
        )

        findings.append(
            Finding(
                check_id=f"codeeval.security.{spec.name}",
                severity=severity,
                title=f"Security hygiene: {spec.name.replace('_', ' ')}",
                rationale=(
                    f"{len(hits)} occurrence(s) in {language}: {spec.explanation}. Found "
                    "by reading the source as text, so confirm the context before "
                    f"treating it as settled.{aside}"
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

"""Depth for TypeScript and JavaScript, without running the candidate's toolchain.

Analysing only Python was the largest fairness problem in this tool. A candidate
whose portfolio is TypeScript got no code-quality evidence at all, which the
ranker correctly reported as "we could not tell" and correctly refused to score
as weak. Correct, and still a bad outcome: the confidence band stayed wide
through no fault of theirs, and the fairness audit named exactly this as the
most likely route to disparate impact in the design.

**Nothing here executes anything from the repository.** The obvious way to get
this depth is `tsc` and `eslint`, and both would run code the candidate wrote:
config files are JavaScript, plugins are arbitrary packages, and `npm install`
runs lifecycle scripts. This tool clones repositories it has every reason to
treat as untrusted, so it reads the source as text instead.

What that buys and what it costs, stated plainly because the dossier says it too:

- Complexity here is counted from decision keywords rather than from a parsed
  syntax tree. On ordinary code it tracks the cyclomatic number closely; on
  heavily generic or deeply nested expressions it can drift.
- There is no type information, so nothing here can find what only a type
  checker would.
- Findings carry lower confidence than their Python counterparts, and their
  evidence names the technique. A weaker measurement must not be presented as
  though it were the stronger one.

Findings reuse the Python check ids on purpose. A complexity problem is the same
concern in either language, and the rubric should weigh it the same way rather
than growing a parallel set of dimensions per language.

What is shared with the other lexically read languages lives in `lexical`. What
is here is what is actually TypeScript-shaped.
"""

from __future__ import annotations

import re
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.codeeval.lexical import (
    SecurityPattern,
    Unit,
    body_end,
    complexity_finding,
    line_of,
    no_tests_finding,
    read_source,
    security_findings,
    strip_spans,
)
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

LANGUAGE = "TypeScript or JavaScript"
COMPLEXITY_THRESHOLD = 15
TRIVIAL_RATIO_THRESHOLD = 0.5

# Lower than the Python analysers, which read a real syntax tree. The number is
# the honest difference between measuring and approximating.
LEXICAL_CONFIDENCE = 0.75

_TEST_DIRECTORIES = {"__tests__", "__test__", "test", "tests", "spec"}
_TEST_SUFFIXES = (".test", ".spec")

# Comments and literals share one alternation so neither can open inside the
# other: a `//` inside a string is not a comment, and a quote inside a comment
# does not open a string.
_COMMENT = r"""//[^\n]*|/\*.*?\*/"""
_LITERAL = r""""(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`"""

NOISE = re.compile(f"{_COMMENT}|{_LITERAL}", re.DOTALL)
COMMENTS_ONLY = re.compile(_COMMENT, re.DOTALL)

# Every construct that adds a branch, and so a path through the function.
_DECISIONS = re.compile(
    r"(?<![\w$])(?:if|for|while|case|catch)(?![\w$])|&&|\|\||\?\?|(?<![?\w$])\?(?!\.)"
)

# The shapes a function takes in this language. Each captures the name so the
# finding can say which one, and each is anchored at the opening brace so the
# body can be found by matching braces from there.
#
# Assignment forms come first. `const named = function (a) {` is matched by both
# the assignment pattern and the bare `function` one, and whichever runs first
# claims the brace: the bare pattern would report it as "(anonymous)" and lose
# the name the reader can actually search for.
_FUNCTIONS = (
    re.compile(
        r"(?<![\w$])(?:const|let|var)\s+([\w$]+)[^=\n]*=\s*(?:async\s+)?\([^)]*\)[^=;]*=>\s*\{"
    ),
    re.compile(r"(?<![\w$])(?:const|let|var)\s+([\w$]+)[^=\n]*=\s*(?:async\s+)?function[^{]*\{"),
    re.compile(r"(?<![\w$])function\s*\*?\s*([\w$]+)?\s*(?:<[^>]*>)?\s*\([^)]*\)[^{;]*\{"),
    re.compile(
        r"(?:^|\n)\s*(?:public|private|protected|static|async|\*|\s)*([\w$]+)\s*"
        r"(?:<[^>]*>)?\s*\([^)]*\)\s*(?::[^{;=]+)?\{"
    ),
)

# Reads as a call, not a definition. Without this every `if (...) {` and
# `catch (e) {` would be reported as a function named "if".
_NOT_FUNCTIONS = frozenset(
    {
        "if", "for", "while", "switch", "catch", "return", "do", "else",
        "function", "class", "try", "finally", "with", "typeof", "await",
        "constructor", "get", "set", "new", "delete", "void", "yield", "import",
    }
)

# Assertions that cannot fail. `expect(true).toBe(true)` is decoration.
_TRIVIAL_ASSERTIONS = (
    re.compile(r"expect\s*\(\s*(?:true|1|!!1)\s*\)\s*\.\s*to(?:Be|Equal|BeTruthy)"),
    re.compile(r"expect\s*\(\s*(?:false|0)\s*\)\s*\.\s*to(?:Be|Equal|BeFalsy)"),
    re.compile(r"assert\s*(?:\.\s*ok\s*)?\(\s*true\s*\)"),
    re.compile(r"expect\s*\(\s*([\w$.]+)\s*\)\s*\.\s*toBe\s*\(\s*\1\s*\)"),
)
_ASSERTION = re.compile(r"(?<![\w$])(?:expect|assert|should)(?![\w$])")

# Security hygiene. Each pattern is chosen to have a low false-positive rate on
# ordinary code, because a false accusation costs a candidate more than a missed
# flag costs a recruiter.
SECURITY_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        "dangerous_eval",
        re.compile(r"(?<![\w$.])eval\s*\(|(?<![\w$.])new\s+Function\s*\("),
        Severity.HIGH,
        "evaluates a string as code, which turns any untrusted input into execution",
    ),
    SecurityPattern(
        "shell_injection",
        re.compile(r"(?:child_process\.)?exec(?:Sync)?\s*\(\s*[`\"'][^`\"')]*\$\{"),
        Severity.HIGH,
        "builds a shell command by interpolation, so input becomes part of the command",
    ),
    SecurityPattern(
        "raw_html_sink",
        re.compile(r"\.innerHTML\s*=(?!=)|dangerouslySetInnerHTML"),
        Severity.MEDIUM,
        "writes unescaped HTML, which is the usual route to cross-site scripting",
    ),
    SecurityPattern(
        "hardcoded_secret",
        re.compile(
            r"(?<![\w$])(?:api[_-]?key|secret|password|passwd|token|private[_-]?key)"
            r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']",
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "a credential appears to be written into the source",
    ),
    SecurityPattern(
        "disabled_tls",
        re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0"),
        Severity.HIGH,
        "turns off TLS certificate verification, which defeats the point of TLS",
    ),
)


def _strip_noise(source: str) -> str:
    """Blank comments and literals. For anything that counts code."""
    return strip_spans(source, NOISE)


def _strip_comments(source: str) -> str:
    """Blank comments, keep literals. For anything that reads what code says."""
    return strip_spans(source, COMMENTS_ONLY)


def _read(path: Path, *, keep_literals: bool = False) -> str | None:
    return read_source(path, NOISE, COMMENTS_ONLY, keep_literals=keep_literals)


def _is_test_file(path: Path) -> bool:
    if any(part in _TEST_DIRECTORIES for part in path.parts):
        return True
    return Path(path.stem).suffix in _TEST_SUFFIXES


def _functions(source: str) -> list[Unit]:
    """Every function-like body, with the decision points inside it counted.

    Bodies are found by brace matching, so a nested function is measured both on
    its own and as part of its parent. That matches how a reader experiences the
    outer function: its branches do not stop being its branches.
    """
    spans: list[Unit] = []
    seen: set[int] = set()

    for pattern in _FUNCTIONS:
        for match in pattern.finditer(source):
            open_brace = source.index("{", match.end() - 1)
            if open_brace in seen:
                continue
            name = match.group(1) or "(anonymous)"
            if name in _NOT_FUNCTIONS:
                continue
            seen.add(open_brace)

            body = source[open_brace : body_end(source, open_brace)]
            spans.append(
                Unit(
                    name=name,
                    line=line_of(source, match.start()),
                    complexity=1 + len(_DECISIONS.findall(body)),
                )
            )

    return spans


def check_typescript_complexity(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    offenders: list[tuple[Path, Unit]] = []

    for path in profile.typescript_files:
        source = _read(path)
        if source is None:
            continue
        offenders.extend(
            (path, span) for span in _functions(source) if span.complexity >= COMPLEXITY_THRESHOLD
        )

    return complexity_finding(
        ctx.full_name,
        profile.root,
        offenders,
        language=LANGUAGE,
        unit="function",
        threshold=COMPLEXITY_THRESHOLD,
        confidence=LEXICAL_CONFIDENCE,
    )


def check_typescript_tests(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    files = profile.typescript_files
    if not files:
        return []

    test_files = [p for p in files if _is_test_file(p)]
    source_files = [p for p in files if not _is_test_file(p)]

    if not test_files:
        return no_tests_finding(
            ctx.full_name,
            profile.root,
            source_files,
            language=LANGUAGE,
            looked_for="*.test.*, *.spec.* or __tests__ files",
            confidence=LEXICAL_CONFIDENCE,
        )

    trivial: list[tuple[Path, int, str]] = []
    total = 0

    for path in test_files:
        source = _read(path)
        if source is None:
            continue
        total += len(_ASSERTION.findall(source))
        for pattern in _TRIVIAL_ASSERTIONS:
            for match in pattern.finditer(source):
                trivial.append((path, line_of(source, match.start()), match.group(0).strip()))

    if not trivial or total == 0:
        return []

    if len(trivial) / total < TRIVIAL_RATIO_THRESHOLD:
        return []

    return [
        Finding(
            check_id="codeeval.trivial_tests",
            severity=Severity.MEDIUM,
            title="Tests assert things that cannot fail",
            rationale=(
                f"{len(trivial)} of {total} assertion(s) compare a literal with itself "
                "or assert a constant. A suite of those passes whatever the code does."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=f"{text} cannot fail",
                )
                for path, line, text in trivial[:5]
            ),
        )
    ]


def check_typescript_security(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    return security_findings(
        ctx.full_name,
        profile.root,
        profile.typescript_files,
        SECURITY_PATTERNS,
        language=LANGUAGE,
        noise=NOISE,
        comments=COMMENTS_ONLY,
        confidence=LEXICAL_CONFIDENCE,
    )

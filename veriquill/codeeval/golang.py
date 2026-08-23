"""Depth for Go, read rather than run.

Same argument as TypeScript, and the same refusal: `go vet` and `staticcheck`
would be the obvious route and both compile the candidate's code, which means
running their generators, their build tags, and whatever their modules pull in.
Veriquill clones repositories it has every reason to treat as untrusted, so it
reads the source as text.

Go is a better fit for this approach than most languages. It has no ternary, no
exceptions, one loop keyword, and gofmt means almost every repository is shaped
the same way. The count of decision keywords tracks the cyclomatic number more
closely here than it does in TypeScript. It is still an approximation and still
says so.

What lives here is what is Go-shaped. The finding construction, the ordering,
the cap at five, and the sentence admitting the count is approximate are shared
with every other language read this way, in `lexical`.

Two checks are genuinely Go's own:

- A test is a function named `TestX` taking `*testing.T`. There is no assertion
  library in the standard library, so a failing test is one that calls
  `t.Error`, `t.Fatal`, or a helper that does. A test function with no such call
  anywhere in its body cannot fail, whatever it looks like.
- `err` discarded into `_` is the language's most common real defect, and it is
  visible lexically. It is reported as code quality rather than security,
  because it is usually haste rather than danger.
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

LANGUAGE = "Go"
COMPLEXITY_THRESHOLD = 15

#: Share of test functions that may assert nothing before it is worth reporting.
HOLLOW_TEST_RATIO = 0.5

#: Discarded errors below this count read as deliberate rather than as a habit.
MIN_IGNORED = 3

# The same number the TypeScript analyser carries, for the same reason: this is
# reading, not parsing, and the confidence should say so.
LEXICAL_CONFIDENCE = 0.75

# Go strings: interpreted in double quotes, raw in backticks with no escapes and
# no interpolation, plus rune literals. Comments are C-shaped.
_COMMENT = r"//[^\n]*|/\*.*?\*/"
_LITERAL = r'"(?:\\.|[^"\\\n])*"|`[^`]*`' + r"|'(?:\\.|[^'\\\n])*'"

NOISE = re.compile(f"{_COMMENT}|{_LITERAL}", re.DOTALL)
COMMENTS_ONLY = re.compile(_COMMENT, re.DOTALL)

# Go's branching vocabulary. `for` covers every loop, `case` covers both switch
# and select, and there is no ternary to account for.
_DECISIONS = re.compile(r"(?<!\w)(?:if|for|case)(?!\w)|&&|\|\|")

# `func Name(` and `func (r *T) Name(`. The receiver form is tried first: a
# method matched by the plain form would lose its name to the receiver.
_FUNCTIONS = (
    re.compile(r"(?<!\w)func\s*\([^)]*\)\s*([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*\([^{]*\{"),
    re.compile(r"(?<!\w)func\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*\([^{]*\{"),
)

_TEST_FUNCTION = re.compile(
    r"(?<!\w)func\s+((?:Test|Benchmark|Fuzz)\w*)\s*\(\s*\w+\s+\*testing\.[TBF]\s*\)\s*\{"
)

# What makes a Go test able to fail: the standard vocabulary, plus the two
# assertion libraries almost everyone reaches for.
_CAN_FAIL = re.compile(
    r"(?<!\w)(?:t|b|f)\.(?:Error|Errorf|Fatal|Fatalf|FailNow|Fail)\b"
    r"|(?<!\w)(?:assert|require)\.\w+\s*\("
    r"|(?<!\w)(?:Expect|Ω)\s*\("
)

# A test that opts out is not a test that passed, and is counted as neither.
_SKIPPED = re.compile(r"(?<!\w)(?:t|b|f)\.Skip(?:Now|f)?\s*\(")

# A returned value discarded into the blank identifier.
_IGNORED_ERROR = re.compile(r"(?<!\w)_\s*(?:,\s*\w+\s*)*(?:,\s*)?=\s*[\w.]+\([^\n]*\)")

SECURITY_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        "disabled_tls",
        re.compile(r"InsecureSkipVerify\s*:\s*true"),
        Severity.HIGH,
        "turns off TLS certificate verification, which defeats the point of TLS",
    ),
    SecurityPattern(
        "shell_injection",
        re.compile(r"exec\.Command(?:Context)?\s*\([^)]*(?:fmt\.Sprintf|\+\s*\w)"),
        Severity.HIGH,
        "builds a command from assembled strings, so input becomes part of the command",
    ),
    SecurityPattern(
        "sql_injection",
        re.compile(
            r"(?:Query|Exec|QueryRow)(?:Context)?\s*\(\s*(?:[\w.]+\s*,\s*)?"
            r'(?:fmt\.Sprintf\s*\(\s*)?"[^"]*(?:SELECT|INSERT|UPDATE|DELETE)[^"]*"\s*\+',
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "builds SQL by concatenation rather than binding parameters",
    ),
    SecurityPattern(
        "hardcoded_secret",
        re.compile(
            r"(?<!\w)(?:apiKey|api_key|secret|password|passwd|token|privateKey)"
            r'\s*(?::=|=)\s*"[^"\s]{12,}"',
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "a credential appears to be written into the source",
    ),
    SecurityPattern(
        "weak_randomness",
        re.compile(r'"math/rand"'),
        Severity.LOW,
        (
            "math/rand is not a cryptographic source; it is fine for jitter and "
            "wrong for anything anyone has to be unable to guess"
        ),
    ),
)


def _strip_noise(source: str) -> str:
    return strip_spans(source, NOISE)


def _read(path: Path, *, keep_literals: bool = False) -> str | None:
    return read_source(path, NOISE, COMMENTS_ONLY, keep_literals=keep_literals)


def _is_test_file(path: Path) -> bool:
    """Go's own rule, and the only one the toolchain honours."""
    return path.name.endswith("_test.go")


def _functions(source: str) -> list[Unit]:
    spans: list[Unit] = []
    seen: set[int] = set()

    for pattern in _FUNCTIONS:
        for match in pattern.finditer(source):
            brace = source.find("{", match.end() - 1)
            if brace < 0 or brace in seen:
                continue
            seen.add(brace)
            body = source[brace : body_end(source, brace)]
            spans.append(
                Unit(
                    name=match.group(1),
                    line=line_of(source, match.start()),
                    complexity=1 + len(_DECISIONS.findall(body)),
                )
            )
    return spans


def check_go_complexity(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    offenders: list[tuple[Path, Unit]] = []

    for path in profile.go_files:
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


def check_go_tests(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    files = profile.go_files
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
            looked_for="*_test.go files",
            confidence=LEXICAL_CONFIDENCE,
        )

    hollow: list[tuple[Path, int, str]] = []
    total = 0

    for path in test_files:
        source = _read(path)
        if source is None:
            continue
        for match in _TEST_FUNCTION.finditer(source):
            brace = source.find("{", match.end() - 1)
            if brace < 0:
                continue
            body = source[brace : body_end(source, brace)]
            if _SKIPPED.search(body):
                # Skipped deliberately. Not a passing test and not a hollow one.
                continue
            total += 1
            if not _CAN_FAIL.search(body):
                hollow.append((path, line_of(source, match.start()), match.group(1)))

    if not hollow or total == 0 or len(hollow) / total < HOLLOW_TEST_RATIO:
        return []

    return [
        Finding(
            check_id="codeeval.trivial_tests",
            severity=Severity.MEDIUM,
            title="Tests that cannot fail",
            rationale=(
                f"{len(hollow)} of {total} test function(s) never call t.Error, t.Fatal, "
                "or an assertion helper, so nothing in them can report a failure. A "
                "suite of those passes whatever the code does."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=f"{name} asserts nothing",
                )
                for path, line, name in hollow[:5]
            ),
        )
    ]


def check_go_error_handling(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    """Errors discarded into `_`.

    Go has no exceptions, so a discarded error is a failure that will never be
    reported anywhere. Assigning to `_` is explicit rather than accidental,
    which is why this is low severity and worth naming rather than ignoring:
    sometimes it is deliberate and correct, and sometimes it is a `defer
    file.Close()` away from losing data.
    """
    ignored: list[tuple[Path, int, str]] = []

    for path in profile.go_files:
        if _is_test_file(path):
            continue
        source = _read(path)
        if source is None:
            continue
        for match in _IGNORED_ERROR.finditer(source):
            ignored.append((path, line_of(source, match.start()), match.group(0).strip()))

    if len(ignored) < MIN_IGNORED:
        # One or two are usually deliberate. A habit is what is worth reporting.
        return []

    return [
        Finding(
            check_id="codeeval.ignored_errors",
            severity=Severity.LOW,
            title="Errors assigned to the blank identifier",
            rationale=(
                f"{len(ignored)} call(s) discard a returned value into `_`. Go has no "
                "exceptions, so an error dropped here is one nothing will ever report. "
                "Some of these are deliberate; read them before treating any as a fault."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=snippet[:120],
                )
                for path, line, snippet in ignored[:5]
            ),
        )
    ]


def check_go_security(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    return security_findings(
        ctx.full_name,
        profile.root,
        profile.go_files,
        SECURITY_PATTERNS,
        language=LANGUAGE,
        noise=NOISE,
        comments=COMMENTS_ONLY,
        confidence=LEXICAL_CONFIDENCE,
        is_test=_is_test_file,
    )

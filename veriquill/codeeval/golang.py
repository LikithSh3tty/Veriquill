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

Two things are genuinely Go-shaped rather than borrowed:

- A test is a function named `TestX` taking `*testing.T`, so a test file is
  found by its `_test.go` suffix and a test by that signature. There is no
  assertion library in the standard library, so a failing test is one that calls
  `t.Error`, `t.Fatal`, or a helper that does. A test function with no such call
  anywhere in its body cannot fail, whatever it looks like.
- `err` being assigned and then never read is the language's most common real
  defect, and it is visible lexically. It is reported as code quality rather
  than security, because it is usually haste rather than danger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.codeeval.lexical import body_end, line_of, strip_spans
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

COMPLEXITY_THRESHOLD = 15

#: Share of test functions that may assert nothing before it is worth reporting.
HOLLOW_TEST_RATIO = 0.5

# The same number the TypeScript analyser carries, for the same reason: this is
# reading, not parsing, and the confidence should say so.
LEXICAL_CONFIDENCE = 0.75

# Go strings: interpreted in double quotes, raw in backticks with no escapes and
# no interpolation, plus rune literals. Comments are C-shaped.
_COMMENT = r"//[^\n]*|/\*.*?\*/"
_LITERAL = r'"(?:\\.|[^"\\\n])*"|`[^`]*`' + r"|'(?:\\.|[^'\\\n])*'"

_NOISE = re.compile(f"{_COMMENT}|{_LITERAL}", re.DOTALL)
_COMMENTS_ONLY = re.compile(_COMMENT, re.DOTALL)

# Go's branching vocabulary. `for` covers every loop, `case` covers both switch
# and select, and there is no ternary to account for.
_DECISIONS = re.compile(r"(?<!\w)(?:if|for|case)(?!\w)|&&|\|\|")

# `func Name(`, `func (r *T) Name(`, and anonymous `func(` for closures. The
# receiver form is tried first: a method matched by the plain form would lose
# its name to the receiver.
_FUNCTIONS = (
    re.compile(r"(?<!\w)func\s*\([^)]*\)\s*([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*\([^{]*\{"),
    re.compile(r"(?<!\w)func\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*\([^{]*\{"),
)

_TEST_FUNCTION = re.compile(
    r"(?<!\w)func\s+((?:Test|Benchmark|Fuzz)\w*)\s*\(\s*\w+\s+\*testing\.[TBF]\s*\)\s*\{"
)

# What makes a Go test able to fail. No assertion library ships with the
# language, so this is the standard vocabulary plus the two libraries almost
# everyone reaches for.
_CAN_FAIL = re.compile(
    r"(?<!\w)(?:t|b|f)\.(?:Error|Errorf|Fatal|Fatalf|FailNow|Fail)\b"
    r"|(?<!\w)(?:assert|require)\.\w+\s*\("
    r"|(?<!\w)(?:Expect|Ω)\s*\("
)

# A test that opts out is not a test that passed, and should not be counted as
# one in either direction.
_SKIPPED = re.compile(r"(?<!\w)(?:t|b|f)\.Skip(?:Now|f)?\s*\(")

# `err` assigned and never mentioned again in the same block. Deliberately
# narrow: it looks only for the assignment being immediately followed by another
# statement that never names err, which is the shape that actually hides a
# failure.
_IGNORED_ERROR = re.compile(r"(?<!\w)_\s*(?:,\s*\w+\s*)*(?:,\s*)?=\s*[\w.]+\([^\n]*\)")

_SECURITY_PATTERNS: tuple[tuple[str, re.Pattern[str], Severity, str], ...] = (
    (
        "disabled_tls",
        re.compile(r"InsecureSkipVerify\s*:\s*true"),
        Severity.HIGH,
        "turns off TLS certificate verification, which defeats the point of TLS",
    ),
    (
        "shell_injection",
        re.compile(r'exec\.Command(?:Context)?\s*\([^)]*(?:fmt\.Sprintf|\+\s*\w)'),
        Severity.HIGH,
        "builds a command from assembled strings, so input becomes part of the command",
    ),
    (
        "sql_injection",
        re.compile(
            r'(?:Query|Exec|QueryRow)(?:Context)?\s*\(\s*(?:[\w.]+\s*,\s*)?'
            r'(?:fmt\.Sprintf\s*\(\s*)?"[^"]*(?:SELECT|INSERT|UPDATE|DELETE)[^"]*"\s*\+',
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "builds SQL by concatenation rather than binding parameters",
    ),
    (
        "hardcoded_secret",
        re.compile(
            r"(?<!\w)(?:apiKey|api_key|secret|password|passwd|token|privateKey)"
            r'\s*(?::=|=)\s*"[^"\s]{12,}"',
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "a credential appears to be written into the source",
    ),
    (
        "weak_randomness",
        re.compile(r'"math/rand"'),
        Severity.LOW,
        (
            "math/rand is not a cryptographic source; it is fine for jitter and "
            "wrong for anything anyone has to be unable to guess"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class FunctionSpan:
    name: str
    line: int
    complexity: int


def _strip_noise(source: str) -> str:
    return strip_spans(source, _NOISE)


def _strip_comments(source: str) -> str:
    return strip_spans(source, _COMMENTS_ONLY)


def _read(path: Path, *, keep_literals: bool = False) -> str | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _strip_comments(source) if keep_literals else _strip_noise(source)


def _is_test_file(path: Path) -> bool:
    """Go's own rule, and the only one the toolchain honours."""
    return path.name.endswith("_test.go")


def _functions(source: str) -> list[FunctionSpan]:
    spans: list[FunctionSpan] = []
    seen: set[int] = set()

    for pattern in _FUNCTIONS:
        for match in pattern.finditer(source):
            brace = source.find("{", match.end() - 1)
            if brace < 0 or brace in seen:
                continue
            seen.add(brace)
            body = source[brace : body_end(source, brace)]
            spans.append(
                FunctionSpan(
                    name=match.group(1),
                    line=line_of(source, match.start()),
                    complexity=1 + len(_DECISIONS.findall(body)),
                )
            )
    return spans


def check_go_complexity(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    offenders: list[tuple[Path, FunctionSpan]] = []

    for path in profile.go_files:
        source = _read(path)
        if source is None:
            continue
        offenders.extend(
            (path, span) for span in _functions(source) if span.complexity >= COMPLEXITY_THRESHOLD
        )

    if not offenders:
        return []

    offenders.sort(key=lambda item: item[1].complexity, reverse=True)
    worst = offenders[:5]

    return [
        Finding(
            check_id="codeeval.high_complexity",
            severity=Severity.MEDIUM if worst[0][1].complexity < 30 else Severity.HIGH,
            title="Functions with high cyclomatic complexity",
            rationale=(
                f"{len(offenders)} Go function(s) reach a branch count of "
                f"{COMPLEXITY_THRESHOLD} or more. The highest is {worst[0][1].name} at "
                f"{worst[0][1].complexity}. Counted from decision keywords rather than "
                "a parsed syntax tree, so treat it as close rather than exact."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=span.line,
                    detail=f"{span.name} branches {span.complexity} ways (lexical count)",
                )
                for path, span in worst
            ),
        )
    ]


def check_go_tests(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    files = profile.go_files
    if not files:
        return []

    test_files = [p for p in files if _is_test_file(p)]
    source_files = [p for p in files if not _is_test_file(p)]

    if source_files and not test_files:
        return [
            Finding(
                check_id="codeeval.no_tests",
                severity=Severity.MEDIUM,
                title="No tests found",
                rationale=(
                    f"{len(source_files)} Go source file(s) and no _test.go files. "
                    "Untested code is not necessarily incorrect, but nothing here "
                    "demonstrates that it works."
                ),
                confidence=LEXICAL_CONFIDENCE,
                evidence=(
                    EvidenceRef(
                        repo=ctx.full_name,
                        path=source_files[0].relative_to(profile.root).as_posix(),
                        detail="no *_test.go files in the repository",
                    ),
                ),
            )
        ]

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
        source = _read(path)
        if source is None or _is_test_file(path):
            continue
        for match in _IGNORED_ERROR.finditer(source):
            ignored.append((path, line_of(source, match.start()), match.group(0).strip()))

    if len(ignored) < 3:
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
    findings: list[Finding] = []

    for name, pattern, severity, explanation in _SECURITY_PATTERNS:
        hits: list[tuple[Path, int, str]] = []
        for path in profile.go_files:
            source = _read(path, keep_literals=True)
            if source is None:
                continue
            for match in pattern.finditer(source):
                hits.append((path, line_of(source, match.start()), match.group(0).strip()))

        if not hits:
            continue

        findings.append(
            Finding(
                check_id=f"codeeval.security.{name}",
                severity=severity,
                title=f"Security hygiene: {name.replace('_', ' ')}",
                rationale=(
                    f"{len(hits)} occurrence(s) in Go: {explanation}. Found by reading "
                    "the source as text, so confirm the context before treating it as "
                    "settled."
                ),
                confidence=LEXICAL_CONFIDENCE,
                evidence=tuple(
                    EvidenceRef(
                        repo=ctx.full_name,
                        path=path.relative_to(profile.root).as_posix(),
                        line=line,
                        detail=snippet[:120],
                    )
                    for path, line, snippet in hits[:5]
                ),
            )
        )

    return findings

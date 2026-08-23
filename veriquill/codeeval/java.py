"""Depth for Java, read rather than run.

The third language on the same terms, and the same refusal: Maven and Gradle
builds execute the candidate's own build scripts, plugins, and annotation
processors before any analyser sees a class file. Veriquill clones repositories
it has every reason to treat as untrusted, so it reads the source as text.

Java is the hardest of the four to read this way. Modifiers stack, generics nest
inside parameter lists, annotations sit between the two, and a constructor looks
like a method with no return type. So method detection here is deliberately
conservative: it would rather miss a method than report a `catch` block as one,
because a complexity figure attributed to something that is not a function is
worse than a complexity figure that is absent.

The Java-shaped check is the swallowed exception. `catch (Exception e) { }` is
this language's version of Go's discarded error: a failure the program has been
told about and will now never mention. It is reported the same way, at low
severity and only once there are enough to read as a habit, because one empty
catch with a comment explaining itself is a decision rather than a defect.

Everything not Java-shaped - the finding construction, the ordering, the caps,
the admission that the count is approximate - lives in `lexical` and is shared.
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

LANGUAGE = "Java"
COMPLEXITY_THRESHOLD = 15
HOLLOW_TEST_RATIO = 0.5
MIN_SWALLOWED = 3

LEXICAL_CONFIDENCE = 0.75

# Text blocks first: `"""..."""` reads as an empty string followed by a quote if
# the ordinary string alternative is tried before it.
_COMMENT = r"//[^\n]*|/\*.*?\*/"
_LITERAL = r'"""(?:.|\n)*?"""' + r'|"(?:\\.|[^"\\\n])*"' + r"|'(?:\\.|[^'\\\n])*'"

NOISE = re.compile(f"{_COMMENT}|{_LITERAL}", re.DOTALL)
COMMENTS_ONLY = re.compile(_COMMENT, re.DOTALL)

# Java has a ternary, unlike Go. The lookbehind keeps it off the `?` of a
# wildcard generic like `List<?>`.
_DECISIONS = re.compile(
    r"(?<!\w)(?:if|for|while|case|catch)(?!\w)|&&|\|\||(?<![<\w?])\?(?![.:?])"
)

# A method or constructor: optional annotations and modifiers, an optional
# return type, a name, a parameter list, an optional throws clause, a brace.
_METHOD = re.compile(
    r"(?:^|[;{}\n])\s*"
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:(?:public|private|protected|static|final|synchronized|abstract|native|default|strictfp)\s+)*"
    r"(?:[\w.$]+(?:<[^;{}]*?>)?(?:\[\])*\s+)?"
    r"([A-Za-z_$][\w$]*)\s*"
    r"\([^;{}]*?\)\s*"
    r"(?:throws\s+[\w.,\s$]+?)?"
    r"\{"
)

# Reads as control flow or a declaration, not a method. Without this, every
# `if (...) {` and `switch (...) {` would be measured as a function.
_NOT_METHODS = frozenset(
    {
        "if", "for", "while", "switch", "catch", "do", "else", "try", "finally",
        "synchronized", "return", "new", "class", "interface", "enum", "record",
        "throw", "assert", "instanceof", "super", "this", "case", "default",
    }
)

_TEST_ANNOTATION = re.compile(r"@(?:Test|ParameterizedTest|RepeatedTest)\b")

# What lets a JUnit test fail. Anything else in the body is setup.
_CAN_FAIL = re.compile(
    r"(?<!\w)(?:assert\w*|fail|verify|expectThrows|assertAll)\s*\("
    r"|(?<!\w)assertThat\s*\("
    r"|\.(?:isEqualTo|isTrue|isFalse|hasSize|contains|isNotNull)\s*\("
)

# Assertions that hold whatever the code does.
_TRIVIAL_ASSERTIONS = (
    re.compile(r"assertTrue\s*\(\s*true\s*\)"),
    re.compile(r"assertFalse\s*\(\s*false\s*\)"),
    re.compile(r"assertNotNull\s*\(\s*new\s+\w+"),
    re.compile(r"assertEquals\s*\(\s*([\w.\"']+)\s*,\s*\1\s*\)"),
)

# `catch (...) { }`: nothing but whitespace between the braces. Literals and
# comments have already been blanked, so a catch whose only content is a comment
# explaining the decision is not counted, which is the intended behaviour.
_SWALLOWED = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")

SECURITY_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        "command_injection",
        re.compile(
            r"(?:Runtime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec|new\s+ProcessBuilder)\s*\([^;]*\+"
        ),
        Severity.HIGH,
        "builds a command from assembled strings, so input becomes part of the command",
    ),
    SecurityPattern(
        "sql_injection",
        re.compile(
            r"(?:executeQuery|executeUpdate|execute)\s*\(\s*[^;)]*\"[^\"]*"
            r"(?:SELECT|INSERT|UPDATE|DELETE)[^\"]*\"[^;)]*\+",
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "builds SQL by concatenation rather than binding parameters",
    ),
    SecurityPattern(
        "hardcoded_secret",
        re.compile(
            r"(?<!\w)(?:apiKey|api_key|secret|password|passwd|token|privateKey)"
            r'\s*=\s*"[^"\s]{12,}"',
            re.IGNORECASE,
        ),
        Severity.HIGH,
        "a credential appears to be written into the source",
    ),
    SecurityPattern(
        "disabled_tls",
        re.compile(
            r"ALLOW_ALL_HOSTNAME_VERIFIER"
            r"|setHostnameVerifier\s*\(\s*\([^)]*\)\s*->\s*true"
            r"|checkServerTrusted\s*\([^)]*\)\s*(?:throws\s+[\w.]+\s*)?\{\s*\}"
        ),
        Severity.HIGH,
        "accepts any certificate or hostname, which defeats the point of TLS",
    ),
    SecurityPattern(
        "unsafe_deserialization",
        re.compile(r"new\s+ObjectInputStream\s*\("),
        Severity.MEDIUM,
        (
            "Java deserialization of untrusted input can execute code before any "
            "of your own runs; confirm the source is trusted"
        ),
    ),
)


def _strip_noise(source: str) -> str:
    return strip_spans(source, NOISE)


def _read(path: Path, *, keep_literals: bool = False) -> str | None:
    return read_source(path, NOISE, COMMENTS_ONLY, keep_literals=keep_literals)


def _is_test_file(path: Path) -> bool:
    """JUnit's conventions, plus Maven's and Gradle's shared directory layout."""
    if "test" in {part.lower() for part in path.parts[:-1]}:
        return True
    stem = path.stem
    return stem.endswith(("Test", "Tests")) or stem.startswith("Test")


def _methods(source: str) -> list[Unit]:
    spans: list[Unit] = []
    seen: set[int] = set()

    for match in _METHOD.finditer(source):
        name = match.group(1)
        if name in _NOT_METHODS:
            continue
        brace = source.rfind("{", match.start(), match.end())
        if brace < 0 or brace in seen:
            continue
        seen.add(brace)
        body = source[brace : body_end(source, brace)]
        spans.append(
            Unit(
                name=name,
                line=line_of(source, match.start(1)),
                complexity=1 + len(_DECISIONS.findall(body)),
            )
        )
    return spans


def _name_after(source: str, brace: int) -> str:
    """The method name preceding an opening brace, for a readable citation."""
    head = source[max(0, brace - 200) : brace]
    names = re.findall(r"([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*$", head)
    return names[-1] if names else "(test)"


def check_java_complexity(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    offenders: list[tuple[Path, Unit]] = []

    for path in profile.java_files:
        source = _read(path)
        if source is None:
            continue
        offenders.extend(
            (path, span) for span in _methods(source) if span.complexity >= COMPLEXITY_THRESHOLD
        )

    return complexity_finding(
        ctx.full_name,
        profile.root,
        offenders,
        language=LANGUAGE,
        unit="method",
        threshold=COMPLEXITY_THRESHOLD,
        confidence=LEXICAL_CONFIDENCE,
    )


def check_java_tests(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    files = profile.java_files
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
            looked_for="*Test.java, *Tests.java, or src/test files",
            confidence=LEXICAL_CONFIDENCE,
        )

    hollow: list[tuple[Path, int, str]] = []
    total = 0

    for path in test_files:
        source = _read(path)
        if source is None:
            continue
        for annotation in _TEST_ANNOTATION.finditer(source):
            brace = source.find("{", annotation.end())
            if brace < 0:
                continue
            body = source[brace : body_end(source, brace)]
            total += 1
            trivial = any(pattern.search(body) for pattern in _TRIVIAL_ASSERTIONS)
            if trivial or not _CAN_FAIL.search(body):
                hollow.append(
                    (path, line_of(source, annotation.start()), _name_after(source, brace))
                )

    if not hollow or total == 0 or len(hollow) / total < HOLLOW_TEST_RATIO:
        return []

    return [
        Finding(
            check_id="codeeval.trivial_tests",
            severity=Severity.MEDIUM,
            title="Tests that cannot fail",
            rationale=(
                f"{len(hollow)} of {total} @Test method(s) either assert nothing or "
                "assert something that holds whatever the code does. A suite of those "
                "passes regardless."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=f"{name} cannot report a failure",
                )
                for path, line, name in hollow[:5]
            ),
        )
    ]


def check_java_exception_handling(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    """Exceptions caught and then not mentioned again.

    An empty catch is a failure the program was told about and will never
    report. Comments are blanked before matching, so a catch whose only content
    is a comment explaining why it is empty does not count: that is a decision,
    and this check is looking for the absence of one.
    """
    swallowed: list[tuple[Path, int, str]] = []

    for path in profile.java_files:
        source = _read(path)
        if source is None:
            continue
        for match in _SWALLOWED.finditer(source):
            swallowed.append((path, line_of(source, match.start()), match.group(0).strip()))

    if len(swallowed) < MIN_SWALLOWED:
        return []

    return [
        Finding(
            check_id="codeeval.swallowed_exceptions",
            severity=Severity.LOW,
            title="Exceptions caught and discarded",
            rationale=(
                f"{len(swallowed)} catch block(s) are empty, so a failure the program "
                "was told about is never reported anywhere. Some of these are "
                "deliberate; read them before treating any as a fault."
            ),
            confidence=LEXICAL_CONFIDENCE,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=" ".join(snippet.split())[:120],
                )
                for path, line, snippet in swallowed[:5]
            ),
        )
    ]


def check_java_security(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    return security_findings(
        ctx.full_name,
        profile.root,
        profile.java_files,
        SECURITY_PATTERNS,
        language=LANGUAGE,
        noise=NOISE,
        comments=COMMENTS_ONLY,
        confidence=LEXICAL_CONFIDENCE,
        is_test=_is_test_file,
    )

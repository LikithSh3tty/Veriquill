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

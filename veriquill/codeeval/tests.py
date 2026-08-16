"""Test quality, not test count.

Counting test files rewards decoration. This inspects the AST for assertions
that actually assert something.
"""

from __future__ import annotations

import ast
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

TRIVIAL_RATIO_THRESHOLD = 0.5


def _is_test_file(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _is_trivial(node: ast.Assert) -> bool:
    """`assert True`, `assert 1`, `assert "x"`: an assertion that cannot fail."""
    test = node.test
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return False


def check_tests(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    if not profile.python_files:
        return []

    test_files = [p for p in profile.python_files if _is_test_file(p)]
    source_files = [p for p in profile.python_files if not _is_test_file(p)]

    if source_files and not test_files:
        return [
            Finding(
                check_id="codeeval.no_tests",
                severity=Severity.MEDIUM,
                title="No tests found",
                rationale=(
                    f"{len(source_files)} Python source file(s) and no test files. "
                    "Untested code is not necessarily incorrect, but nothing here "
                    "demonstrates that it works."
                ),
                confidence=0.9,
                evidence=(
                    EvidenceRef(
                        repo=ctx.full_name,
                        path=source_files[0].relative_to(profile.root).as_posix(),
                        detail="no test_*.py or *_test.py files in the repository",
                    ),
                ),
            )
        ]

    total_asserts = 0
    trivial_refs: list[EvidenceRef] = []
    trivial_count = 0

    for path in test_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            total_asserts += 1
            if _is_trivial(node):
                trivial_count += 1
                if len(trivial_refs) < 5:
                    trivial_refs.append(
                        EvidenceRef(
                            repo=ctx.full_name,
                            path=path.relative_to(profile.root).as_posix(),
                            line=node.lineno,
                            detail="assertion cannot fail",
                        )
                    )

    if total_asserts == 0 or not trivial_refs:
        return []

    ratio = trivial_count / total_asserts
    if ratio < TRIVIAL_RATIO_THRESHOLD:
        return []

    return [
        Finding(
            check_id="codeeval.trivial_tests",
            severity=Severity.MEDIUM,
            title="Tests present but trivial",
            rationale=(
                f"{trivial_count} of {total_asserts} assertions ({ratio:.0%}) cannot "
                "fail, so the test suite reports success regardless of the code's "
                "behaviour."
            ),
            confidence=0.9,
            evidence=tuple(trivial_refs),
        )
    ]

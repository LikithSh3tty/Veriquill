"""Test quality, not test count.

Counting test files rewards decoration. This inspects the AST for assertions
that actually assert something.

Every way a Python test can fail counts, not only the bare `assert`
statement. Counting only that penalised whole testing styles: a twenty-case
unittest suite with one `assert True` smoke test was reported as "1 of 1
assertions cannot fail", at medium severity and the highest confidence any
check here carries, because `self.assertEqual` is a call and not an assert
node. The same repository written in plain pytest was reported as fine. That
is a judgment about which library the candidate chose, dressed up as a
judgment about their tests.
"""

from __future__ import annotations

import ast

from veriquill.codeeval.detect import LanguageProfile, is_python_test_file
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

TRIVIAL_RATIO_THRESHOLD = 0.5


_is_test_file = is_python_test_file


def _is_trivial(node: ast.Assert) -> bool:
    """`assert True`, `assert 1`, `assert "x"`: an assertion that cannot fail."""
    test = node.test
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return False


def _called_name(node: ast.Call) -> str:
    """The bare name of whatever is being called."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_assertion_call(node: ast.AST) -> bool:
    """A call that can fail a test.

    Covers unittest's `self.assertEqual`, the numpy and pandas
    `assert_*` helpers, `mock.assert_called_with`, and a bare `fail()`.
    Only test files are walked, so an `assert_`-prefixed helper found here is
    a test asserting something.
    """
    if not isinstance(node, ast.Call):
        return False
    name = _called_name(node)
    return name.startswith("assert") or name == "fail"


def _is_raises_block(node: ast.AST) -> bool:
    """`with pytest.raises(...)`: the assertion is that it raised."""
    if not isinstance(node, (ast.With, ast.AsyncWith)):
        return False
    return any(
        isinstance(item.context_expr, ast.Call)
        and _called_name(item.context_expr) in {"raises", "assertRaises", "warns"}
        for item in node.items
    )


def _is_trivial_call(node: ast.Call) -> bool:
    """`assertTrue(True)`, `assertEqual(1, 1)`: holds whatever the code does."""
    name = _called_name(node)
    args = [a for a in node.args if not isinstance(a, ast.Starred)]

    if name in {"assertTrue", "assertFalse"} and len(args) == 1:
        return isinstance(args[0], ast.Constant)
    if name in {"assertEqual", "assertEquals", "assertIs"} and len(args) == 2:
        left, right = args
        return (
            isinstance(left, ast.Constant)
            and isinstance(right, ast.Constant)
            and left.value == right.value
        )
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
            trivial = False
            if isinstance(node, ast.Assert):
                trivial = _is_trivial(node)
            elif _is_assertion_call(node):
                trivial = _is_trivial_call(node)  # type: ignore[arg-type]
            elif _is_raises_block(node):
                # An expectation that something raises cannot be vacuous.
                pass
            else:
                continue

            total_asserts += 1
            if trivial:
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

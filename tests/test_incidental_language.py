"""A language a repository barely contains cannot be judged for lacking tests.

Three real repositories, measured. bradfitz/go-redox is 11,277 Go files, nine
JavaScript and two Python, and earned a finding for having no Python tests.
mitsuhiko/insta is 56 Rust files carrying a large test suite and eight
TypeScript, and earned one for having no TypeScript tests. Both sentences are
true of the files they count and neither is true of the repository it names.

bradfitz/koffer is the control: 15 Java files and 11 JavaScript, both genuinely
without tests, and both worth saying.
"""

from __future__ import annotations

from pathlib import Path

from veriquill.codeeval.lexical import is_incidental, no_tests_finding


def _files(n: int) -> list[Path]:
    return [Path(f"/repo/src/file{i}.x") for i in range(n)]


def test_two_python_files_beside_eleven_thousand_go_files_say_nothing():
    assert is_incidental(_files(2), 11_277 + 9 + 2)


def test_a_test_suite_in_another_language_is_not_absence_of_tests():
    """insta's tests are Rust; the eight TypeScript files are its website."""
    assert is_incidental(_files(8), 56 + 8)


def test_a_language_that_is_most_of_the_repository_is_still_judged():
    """koffer really is 15 Java files with no tests, and that is worth saying."""
    assert not is_incidental(_files(15), 15 + 11)
    assert not is_incidental(_files(11), 15 + 11)


def test_a_single_language_repository_is_never_incidental_to_itself():
    """The ordinary case must not regress: all of it is the repository."""
    assert not is_incidental(_files(3), 3)


def test_the_finding_is_withheld_rather_than_softened():
    """Nothing is reported at all, because the claim would be about the wrong thing."""
    assert (
        no_tests_finding(
            "bradfitz/go-redox",
            Path("/repo"),
            _files(2),
            language="Python",
            looked_for="test files",
            confidence=0.9,
            repository_files=11_288,
        )
        == []
    )


def test_the_finding_still_lands_when_the_language_carries_the_repository():
    findings = no_tests_finding(
        "bradfitz/koffer",
        Path("/repo/src"),
        [Path("/repo/src/Main.java")] * 15,
        language="Java",
        looked_for="test files",
        confidence=0.9,
        repository_files=26,
    )

    assert [f.check_id for f in findings] == ["codeeval.no_tests"]


def test_an_unknown_composition_is_not_treated_as_a_licence_to_judge():
    """A caller that cannot say what the repository holds gets silence, not a flag."""
    assert is_incidental(_files(5), 0)


def test_the_composition_has_to_be_supplied():
    """With a default it would be omitted, and the check would go quiet unnoticed.

    Defaulting this to zero meant any caller that forgot it suppressed every
    finding it could ever raise, and every test of that caller would still
    pass. Analysers have been silently disconnected in this codebase before.
    """
    import inspect

    parameter = inspect.signature(no_tests_finding).parameters["repository_files"]
    assert parameter.default is inspect.Parameter.empty

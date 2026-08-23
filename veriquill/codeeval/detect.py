"""Language detection and the authored-file inventory every analyser uses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from veriquill.vendored import authored_files

EXTENSION_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sql": "SQL",
    ".sh": "Shell",
}

# Languages an analyser actually inspects, as opposed to counts. Anything
# outside this set is reported as detected and unread, because silence about a
# language would read as a clean bill of health.
DEEPLY_ANALYSED = {"Python", "TypeScript", "JavaScript", "Go", "Java"}

#: The languages `typescript_files` collects. They share a grammar closely
#: enough that one lexical analyser serves both, and a repository mixing them
#: is one codebase rather than two.
TYPESCRIPT_LANGUAGES = {"TypeScript", "JavaScript"}


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    languages: dict[str, int] = field(default_factory=dict)
    python_files: list[Path] = field(default_factory=list)
    typescript_files: list[Path] = field(default_factory=list)
    go_files: list[Path] = field(default_factory=list)
    java_files: list[Path] = field(default_factory=list)
    total_loc: int = 0
    root: Path = Path(".")


def is_python_test_file(path: Path) -> bool:
    """Both conventions pytest collects, plus the directory it collects from.

    This lives here because two analysers were deciding it separately and
    disagreeing. `tests.py` knew `test_*.py` and `*_test.py`; `structure.py`
    knew only the first, so a candidate who names their files `parser_test.py`
    had every one of them reported as a module nothing imports. The naming
    convention they chose is not a defect.
    """
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return True
    return any(part in {"tests", "test"} for part in path.parts[:-1])


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def profile_repo(root: Path) -> LanguageProfile:
    languages: dict[str, int] = {}
    python_files: list[Path] = []
    typescript_files: list[Path] = []
    go_files: list[Path] = []
    java_files: list[Path] = []
    total_loc = 0

    for relative in authored_files(root):
        language = EXTENSION_LANGUAGES.get(relative.suffix.lower())
        if language is None:
            continue
        languages[language] = languages.get(language, 0) + 1
        total_loc += _count_lines(root / relative)
        if language == "Python":
            python_files.append(root / relative)
        elif language in TYPESCRIPT_LANGUAGES:
            typescript_files.append(root / relative)
        elif language == "Go":
            go_files.append(root / relative)
        elif language == "Java":
            java_files.append(root / relative)

    return LanguageProfile(
        languages=languages,
        python_files=python_files,
        typescript_files=typescript_files,
        go_files=go_files,
        java_files=java_files,
        total_loc=total_loc,
        root=root,
    )

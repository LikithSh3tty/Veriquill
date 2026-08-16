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

DEEPLY_ANALYSED = {"Python"}


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    languages: dict[str, int] = field(default_factory=dict)
    python_files: list[Path] = field(default_factory=list)
    total_loc: int = 0
    root: Path = Path(".")


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def profile_repo(root: Path) -> LanguageProfile:
    languages: dict[str, int] = {}
    python_files: list[Path] = []
    total_loc = 0

    for relative in authored_files(root):
        language = EXTENSION_LANGUAGES.get(relative.suffix.lower())
        if language is None:
            continue
        languages[language] = languages.get(language, 0) + 1
        total_loc += _count_lines(root / relative)
        if language == "Python":
            python_files.append(root / relative)

    return LanguageProfile(
        languages=languages,
        python_files=python_files,
        total_loc=total_loc,
        root=root,
    )

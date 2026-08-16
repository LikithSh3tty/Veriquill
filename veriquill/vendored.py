"""Separating authored code from code the candidate merely acquired.

Every metric in Veriquill excludes vendored and generated paths. Counting
`node_modules` as a candidate's work would inflate both size and quality
scores, which section 4 of the specification names as template inflation.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

VENDORED_DIRS = {
    "node_modules",
    "vendor",
    "vendors",
    "third_party",
    "thirdparty",
    "dist",
    "build",
    "out",
    "bower_components",
    "site-packages",
    "migrations",
    ".venv",
    "venv",
    "env",
    ".git",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".next",
    ".nuxt",
    "target",
}

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "go.sum",
}

GENERATED_SUFFIXES = (".min.js", ".min.css", ".bundle.js", "_pb2.py", ".g.dart")


def is_vendored(path: str) -> bool:
    pure = PurePosixPath(path.replace("\\", "/"))
    if any(part in VENDORED_DIRS for part in pure.parts):
        return True
    if pure.name in LOCKFILES:
        return True
    return pure.name.endswith(GENERATED_SUFFIXES)


def authored_files(root: Path) -> list[Path]:
    """Non-vendored files under `root`, as paths relative to `root`."""
    results: list[Path] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if is_vendored(relative.as_posix()):
            continue
        results.append(relative)
    return sorted(results)

"""Module structure: modules nothing imports and cannot be entry points."""

from __future__ import annotations

import ast
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

_ENTRYPOINT_NAMES = {
    "__init__.py",
    "__main__.py",
    "main.py",
    "app.py",
    "cli.py",
    "setup.py",
    "conftest.py",
}
_MIN_MODULES = 5


def _module_name(path: Path, root: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix().replace("/", ".")


def check_structure(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    modules = [p for p in profile.python_files if p.name not in _ENTRYPOINT_NAMES]
    if len(modules) < _MIN_MODULES:
        return []

    imported: set[str] = set()
    for path in profile.python_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
                for alias in node.names:
                    imported.add(alias.name)

    orphans = [
        path
        for path in modules
        if _module_name(path, profile.root).split(".")[-1] not in imported
        and not path.name.startswith("test_")
    ]

    if len(orphans) < 2:
        return []

    return [
        Finding(
            check_id="codeeval.unreferenced_modules",
            severity=Severity.LOW,
            title="Modules that nothing imports",
            rationale=(
                f"{len(orphans)} module(s) are never imported anywhere in the "
                "repository and are not conventional entry points. They may be dead "
                "code, or they may be invoked by tooling this analysis cannot see."
            ),
            confidence=0.5,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    detail="no import of this module found",
                )
                for path in orphans[:5]
            ),
        )
    ]

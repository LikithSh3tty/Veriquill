"""Module structure: modules nothing imports and cannot be entry points.

The check is only as good as its idea of what an entry point is, and a module
reached by configuration is not dead just because no import statement names
it. A Django layout drew four findings for `manage.py`, `settings.py`,
`urls.py`, and `asgi.py`, every one of which is invoked by the framework
through a string. Being marked down for choosing Django is not a code-quality
signal.

It errs toward silence for the reason the rest of this package does: a false
accusation costs a candidate more than a missed flag costs a recruiter. Each
name excluded here is one that can no longer be reported, which weakens the
check; reporting a framework's own conventions as dead code would make it
wrong.
"""

from __future__ import annotations

import ast
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile, is_python_test_file
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

# Invoked by a runtime, a framework, or a packaging entry point rather than
# by an import statement, so 'nothing imports it' is true and says nothing.
_ENTRYPOINT_NAMES = {
    "__init__.py",
    "__main__.py",
    "main.py",
    "app.py",
    "cli.py",
    "setup.py",
    "conftest.py",
    # Django and the layouts that copy it
    "manage.py",
    "settings.py",
    "urls.py",
    "wsgi.py",
    "asgi.py",
    "admin.py",
    "apps.py",
    # Task runners and servers started by name
    "celery.py",
    "tasks.py",
    "routes.py",
    "run.py",
    "server.py",
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
        and not is_python_test_file(path)
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

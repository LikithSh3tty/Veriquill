"""Lint compliance, via ruff."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

VIOLATIONS_PER_KLOC_THRESHOLD = 20.0


def _relative(filename: str, root: Path) -> str:
    try:
        return Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(filename).name


def check_style(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    if not profile.python_files or profile.total_loc == 0:
        return []

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                str(profile.root),
                "--output-format",
                "json",
                "--no-cache",
            ],
            capture_output=True,
            text=True,
            timeout=settings.analyser_timeout_seconds,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []

    if not violations:
        return []

    per_kloc = len(violations) / max(profile.total_loc / 1000, 0.001)
    if per_kloc < VIOLATIONS_PER_KLOC_THRESHOLD:
        return []

    return [
        Finding(
            check_id="codeeval.lint_debt",
            severity=Severity.LOW,
            title="Lint compliance is weak",
            rationale=(
                f"{len(violations)} lint violations across roughly {profile.total_loc} "
                f"lines ({per_kloc:.0f} per thousand lines). Style is a weak signal on "
                "its own and says nothing about correctness."
            ),
            confidence=0.7,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=_relative(v["filename"], profile.root),
                    line=(v.get("location") or {}).get("row"),
                    detail=f"{v.get('code')}: {v.get('message')}"[:200],
                )
                for v in violations[:5]
            ),
        )
    ]

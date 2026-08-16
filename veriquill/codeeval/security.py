"""Security hygiene, via bandit.

Bandit runs as a subprocess so a crash inside it cannot take down the run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

_SEVERITY_MAP = {
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}


def _relative(filename: str, root: Path) -> str:
    try:
        return Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(filename).name


def check_security(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    if not profile.python_files:
        return []

    try:
        result = subprocess.run(
            [sys.executable, "-m", "bandit", "-r", str(profile.root), "-f", "json", "-q"],
            capture_output=True,
            text=True,
            timeout=settings.analyser_timeout_seconds,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    try:
        report = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []

    grouped: dict[tuple[str, str], list[dict]] = {}
    for issue in report.get("results", []):
        key = (issue["test_id"], issue["issue_severity"].upper())
        grouped.setdefault(key, []).append(issue)

    findings: list[Finding] = []
    for (test_id, severity_name), issues in grouped.items():
        severity = _SEVERITY_MAP.get(severity_name, Severity.LOW)
        first = issues[0]
        findings.append(
            Finding(
                check_id=f"codeeval.security.{test_id.lower()}",
                severity=severity,
                title=first["issue_text"][:120],
                rationale=(
                    f"{len(issues)} occurrence(s) of {test_id}: {first['issue_text']} "
                    "Each is reported with the file and line that produced it."
                ),
                confidence=0.8 if first.get("issue_confidence") == "HIGH" else 0.6,
                evidence=tuple(
                    EvidenceRef(
                        repo=ctx.full_name,
                        path=_relative(issue["filename"], profile.root),
                        line=issue["line_number"],
                        detail=issue["issue_text"][:200],
                    )
                    for issue in issues[:5]
                ),
            )
        )

    return findings

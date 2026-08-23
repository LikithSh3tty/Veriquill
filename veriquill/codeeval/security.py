"""Security hygiene, via bandit.

Bandit runs as a subprocess so a crash inside it cannot take down the run.

It is pointed at the candidate's own files rather than at the repository
root. Recursing the root meant it read vendored trees: a repository whose
single authored file was clean drew four security findings, every one of
them citing a file inside `node_modules`. Those flowed into the security
dimension and lowered a real candidate's score for code they did not write.
"""

from __future__ import annotations

from pathlib import Path

from veriquill.codeeval.detect import LanguageProfile
from veriquill.codeeval.runner import python_tool, run_json
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


def _is_noise(issue: dict) -> bool:
    """Findings that are correct in general but meaningless here.

    B101 (assert_used) fires on every `assert` statement. In a test file that
    is the entire point of the file, so reporting it would penalise a
    candidate for writing tests.
    """
    if issue.get("test_id") != "B101":
        return False
    name = Path(issue.get("filename", "")).name
    return name.startswith("test_") or name.endswith("_test.py")


def check_security(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    if not profile.python_files:
        return []

    reports = run_json(
        python_tool("bandit", "-f", "json", "-q"),
        profile.python_files,
        settings.analyser_timeout_seconds,
    )

    grouped: dict[tuple[str, str], list[dict]] = {}
    for issue in [i for report in reports for i in (report or {}).get("results", [])]:
        if _is_noise(issue):
            continue
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

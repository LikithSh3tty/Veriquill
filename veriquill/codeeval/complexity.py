"""Cyclomatic complexity and maintainability, via radon."""

from __future__ import annotations

from pathlib import Path

from radon.complexity import cc_visit

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity

COMPLEXITY_THRESHOLD = 15


def check_complexity(
    ctx: RepoContext, profile: LanguageProfile, settings: Settings
) -> list[Finding]:
    offenders: list[tuple[Path, str, int, int]] = []

    for path in profile.python_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            blocks = cc_visit(source)
        except (OSError, SyntaxError):
            continue
        for block in blocks:
            if block.complexity >= COMPLEXITY_THRESHOLD:
                offenders.append((path, block.name, block.lineno, block.complexity))

    if not offenders:
        return []

    offenders.sort(key=lambda item: item[3], reverse=True)
    worst = offenders[:5]

    return [
        Finding(
            check_id="codeeval.high_complexity",
            severity=Severity.MEDIUM if worst[0][3] < 30 else Severity.HIGH,
            title="Functions with high cyclomatic complexity",
            rationale=(
                f"{len(offenders)} function(s) score at or above complexity "
                f"{COMPLEXITY_THRESHOLD}. The highest is {worst[0][1]} at "
                f"{worst[0][3]}. High complexity raises defect risk and makes the "
                "code hard to change."
            ),
            confidence=0.95,
            evidence=tuple(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=path.relative_to(profile.root).as_posix(),
                    line=line,
                    detail=f"{name} has complexity {score}",
                )
                for path, name, line, score in worst
            ),
        )
    ]

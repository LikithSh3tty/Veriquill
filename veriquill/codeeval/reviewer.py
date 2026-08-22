"""Optional design review by a language model (specification §5, §13).

Static analysis measures. It counts branches, finds a hardcoded secret, notices
that nothing imports a module. What it cannot do is say "authentication is
decided in four different places here", which is the kind of judgment a senior
reviewer forms in a minute and no metric captures.

So a model is allowed to phrase that judgment, under rules that keep it from
laundering an opinion into a measurement:

1. **It cites or it is discarded.** Every observation must quote a line that
   appears verbatim at the file and line number it names. A quote the file does
   not contain is dropped, not surfaced with an invented citation.
2. **It cannot outrank a measurement.** Severity is capped at medium and
   confidence at 0.5, so a subjective reading never sorts above a deterministic
   authenticity flag in the red-flag register.
3. **It never reports a number.** The model returns prose about design and a
   quote. Every metric in the dossier still comes from static analysis.
4. **It is off by default and optional.** Without the setting enabled, or
   without credentials, nothing runs and the pipeline stays fully
   deterministic.
5. **It only ever sees authored code.** Vendored trees are excluded before the
   request is built.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from veriquill.codeeval.detect import LanguageProfile
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.llm import build_client

logger = logging.getLogger(__name__)

MAX_CONFIDENCE = 0.5
MAX_OBSERVATIONS = 10
MAX_FILES = 12
MAX_FILE_BYTES = 20_000

# A judgment must never sort above something that was measured.
_ALLOWED_SEVERITY = {"low": Severity.LOW, "medium": Severity.MEDIUM}
_SEVERITY_CAP = Severity.MEDIUM
# A model that reaches for "critical" is still saying "this matters more". That
# ordering is worth keeping; its ceiling is not. So an over-severe judgment is
# clamped to the cap rather than demoted to the floor, and anything
# unrecognisable falls to low.
_ABOVE_CAP = {"critical", "high"}

_SYSTEM = """You review Python for design quality, the way a senior engineer would in a
code review.

Report only what the code shows: responsibilities that are split or tangled,
duplicated decisions, error handling that hides failures, abstractions that
leak, names that mislead. Say what a maintainer would find harder because of it.

Rules you must follow:
- `quote` must be copied verbatim from the single line you name in `line`. If
  you cannot quote a line exactly, do not report the observation.
- Do not report metrics, counts, scores, or percentages. Those are measured
  elsewhere and yours would be guesses.
- Do not comment on formatting, style, or anything a linter already covers.
- Do not speculate about the author. Judge the code, never the person."""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "quote": {"type": "string"},
                    "concern": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium"]},
                },
                "required": ["path", "line", "quote", "concern"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["observations"],
    "additionalProperties": False,
}


class DesignReviewer:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> Any | None:
        return build_client(
            self._settings,
            enabled=self._settings.code_review_enabled,
            purpose="design review",
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    def review(self, ctx: RepoContext, profile: LanguageProfile) -> list[Finding]:
        if self._client is None or not profile.python_files:
            return []

        sources = self._collect(ctx.path, profile)
        if not sources:
            return []

        payload = self._ask(ctx.full_name, sources)
        if payload is None:
            return []

        findings: list[Finding] = []
        for item in payload.get("observations", [])[:MAX_OBSERVATIONS]:
            finding = self._ground(item, ctx)
            if finding is not None:
                findings.append(finding)

        return findings

    @staticmethod
    def _collect(root: Path, profile: LanguageProfile) -> list[tuple[str, str]]:
        """Read the authored Python the model is allowed to see.

        `profile.python_files` already excludes vendored trees, so nothing that
        the candidate did not write is ever sent.
        """
        sources: list[tuple[str, str]] = []
        for relative in sorted(profile.python_files)[:MAX_FILES]:
            path = root / relative
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                continue
            sources.append((relative.as_posix(), text))
        return sources

    def _ask(self, repo: str, sources: list[tuple[str, str]]) -> dict[str, Any] | None:
        body = "\n\n".join(
            f"=== {name} ===\n"
            + "\n".join(f"{n}: {line}" for n, line in enumerate(text.splitlines(), start=1))
            for name, text in sources
        )

        try:
            response = self._client.messages.create(
                model=self._settings.code_review_model,
                max_tokens=self._settings.code_review_max_tokens,
                system=_SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{"role": "user", "content": f"Repository: {repo}\n\n{body}"}],
            )
        except Exception:
            logger.exception("design review request failed for %s", repo)
            return None

        if getattr(response, "stop_reason", None) == "refusal":
            logger.info("design review refused for %s", repo)
            return None

        text = next(
            (b.text for b in response.content if getattr(b, "type", None) == "text"), ""
        )
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("design review returned unparseable output for %s", repo)
            return None

        return parsed if isinstance(parsed, dict) else None

    def _ground(self, item: dict[str, Any], ctx: RepoContext) -> Finding | None:
        """Accept an observation only if the line it quotes is really there."""
        raw_path = str(item.get("path", "")).strip()
        quote = str(item.get("quote", "")).strip()
        concern = str(item.get("concern", "")).strip()
        if not raw_path or not quote or not concern:
            return None

        try:
            line_number = int(item.get("line", 0))
        except (TypeError, ValueError):
            return None
        if line_number < 1:
            return None

        target = (ctx.path / raw_path).resolve()
        try:
            # A path that escapes the clone is not a citation, it is an attempt
            # to read something that was never part of this candidate's work.
            target.relative_to(ctx.path.resolve())
        except ValueError:
            logger.info("dropping observation outside the repository: %r", raw_path)
            return None

        if not target.is_file():
            return None

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None

        if line_number > len(lines):
            return None
        if lines[line_number - 1].strip() != quote.strip():
            logger.info("dropping ungrounded observation at %s:%s", raw_path, line_number)
            return None

        stated = str(item.get("severity", "low")).strip().lower()
        severity = (
            _SEVERITY_CAP if stated in _ABOVE_CAP else _ALLOWED_SEVERITY.get(stated, Severity.LOW)
        )

        return Finding(
            check_id="codeeval.design_review",
            severity=severity,
            title=concern if len(concern) <= 120 else f"{concern[:117]}...",
            rationale=(
                f"{concern} This is a reviewer's judgment about design, not a "
                "measurement: it is offered as a question to raise, and every "
                "metric in this dossier comes from static analysis instead."
            ),
            confidence=MAX_CONFIDENCE,
            evidence=(
                EvidenceRef(
                    repo=ctx.full_name,
                    path=raw_path,
                    line=line_number,
                    detail=lines[line_number - 1].strip(),
                ),
            ),
        )

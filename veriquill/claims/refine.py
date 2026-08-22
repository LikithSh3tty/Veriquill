"""Optional LLM pass over a resume the structural parser has already read.

Two rules make this safe to trust:

1. It only ever *phrases* claims. Every claim it returns must quote text that
   actually appears in the document, and the quote is matched back to a real
   line number. A claim attributed to text the document does not contain is
   discarded rather than surfaced with a fabricated citation.
2. It is optional. With no credentials configured the refiner reports itself
   unavailable and returns nothing, so the pipeline degrades to the
   deterministic parsers instead of failing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from veriquill.claims.documents import Document
from veriquill.claims.models import Claim, ClaimKind, ClaimSource
from veriquill.config import Settings
from veriquill.llm import build_client

logger = logging.getLogger(__name__)

_SYSTEM = """You extract claims a candidate makes about themselves from their resume.

A claim is something the candidate asserts: a role they held, a skill they have,
a project they built, an achievement, or a qualification. You are not judging
whether any of it is true, and you must not infer anything the text does not say.

For every claim, `excerpt` must be copied verbatim from a single line of the
document. If you cannot quote a line exactly, do not emit the claim."""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [k.value for k in ClaimKind],
                    },
                    "text": {"type": "string"},
                    "subject": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
                "required": ["kind", "text", "excerpt"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


class ClaimRefiner:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> Any | None:
        """Construct an Anthropic client, or None when this pass cannot run."""
        return build_client(
            self._settings,
            enabled=self._settings.claim_refinement_enabled,
            purpose="claim refinement",
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    def refine(self, document: Document, existing: list[Claim]) -> list[Claim]:
        if self._client is None:
            return []

        payload = self._ask(document)
        if payload is None:
            return []

        seen = {(c.kind, c.text.strip().lower()) for c in existing}
        # A rephrasing is still the same claim. The structural parser already
        # read every line it understood, so a line it covered for this kind is
        # not available for the model to restate in different words.
        covered = {(c.kind, c.source.locator) for c in existing}
        refined: list[Claim] = []

        for item in payload.get("claims", []):
            claim = self._ground(item, document)
            if claim is None:
                continue
            if (claim.kind, claim.source.locator) in covered:
                continue
            key = (claim.kind, claim.text.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            covered.add((claim.kind, claim.source.locator))
            refined.append(claim)

        return refined

    def _ask(self, document: Document) -> dict[str, Any] | None:
        numbered = "\n".join(
            f"{n}: {line}" for n, line in enumerate(document.lines, start=1)
        )
        try:
            response = self._client.messages.create(
                model=self._settings.claim_model,
                max_tokens=self._settings.claim_max_tokens,
                system=_SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[
                    {
                        "role": "user",
                        "content": f"Document: {document.name}\n\n{numbered}",
                    }
                ],
            )
        except Exception:
            logger.exception("claim refinement request failed for %s", document.name)
            return None

        if getattr(response, "stop_reason", None) == "refusal":
            logger.info("claim refinement refused for %s", document.name)
            return None

        text = next(
            (b.text for b in response.content if getattr(b, "type", None) == "text"),
            "",
        )
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("claim refinement returned unparseable output")
            return None

    @staticmethod
    def _ground(item: dict[str, Any], document: Document) -> Claim | None:
        """Accept a claim only if its excerpt really appears in the document."""
        excerpt = str(item.get("excerpt", "")).strip()
        text = str(item.get("text", "")).strip()
        if not excerpt or not text:
            return None

        line_number = document.line_number_of(excerpt)
        if line_number is None:
            logger.info("dropping ungrounded claim: %r", text)
            return None

        try:
            kind = ClaimKind(str(item.get("kind", "")).strip().lower())
        except ValueError:
            return None

        subject = str(item.get("subject", "")).strip().lower() or None
        return Claim(
            kind=kind,
            text=text,
            source=ClaimSource(
                document=document.name,
                locator=f"line {line_number}",
                excerpt=document.lines[line_number - 1],
            ),
            subject=subject,
        )

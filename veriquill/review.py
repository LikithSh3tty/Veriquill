"""The human review gate and its audit log.

Two properties matter more than convenience here. Nothing leaves the tool
without a named human having seen it, and nothing a human does can make the
machine result disappear: overrides sit beside it, with a reason, and the whole
history replays from the log.

Later actions supersede earlier ones for the same flag, so a reviewer can change
their mind. The earlier action stays in the log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from veriquill.models import (
    CandidateResponse,
    ComparisonEntry,
    ComparisonRecord,
    ReviewAction,
)
from veriquill.rank.compare import compare
from veriquill.store import load_rubric

FLAG_ACTIONS = frozenset({"flag_dismiss", "flag_confirm"})
ACTIONS = FLAG_ACTIONS | {"band_override"}

DISCLAIMER = (
    "This export is advisory. It records what Veriquill measured, what a named "
    "human changed, and why. It is not a hiring decision."
)


class ReviewError(ValueError):
    """Raised when a review action or an export cannot be honoured."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry(comparison: ComparisonRecord, candidate: str) -> ComparisonEntry:
    for entry in comparison.entries:
        if entry.candidate_handle == candidate:
            return entry
    known = ", ".join(sorted(e.candidate_handle for e in comparison.entries))
    raise ReviewError(f"{candidate!r} is not in this comparison; it holds: {known}")


def _flag_ids(entry: ComparisonEntry) -> set[str]:
    register = (entry.dossier.payload or {}).get("red_flag_register") or []
    return {str(flag.get("flag_id")) for flag in register}


def _actions(session: Session, comparison: ComparisonRecord) -> list[ReviewAction]:
    return list(
        session.scalars(
            select(ReviewAction)
            .where(ReviewAction.comparison_id == comparison.id)
            .order_by(ReviewAction.id)
        ).all()
    )


def _append(
    session: Session,
    comparison: ComparisonRecord,
    *,
    actor: str,
    action: str,
    reason: str,
    entry_id: int | None,
    target: str | None,
) -> ReviewAction:
    record = ReviewAction(
        comparison_id=comparison.id,
        entry_id=entry_id,
        actor=actor,
        action=action,
        target=target,
        reason=reason,
        revision=comparison.revision,
        created_at=_now(),
    )
    session.add(record)
    session.flush()
    return record


def record_action(
    session: Session,
    comparison: ComparisonRecord,
    *,
    actor: str,
    action: str,
    candidate: str,
    reason: str,
    target: str | None = None,
) -> ReviewAction:
    actor = (actor or "").strip()
    if not actor:
        raise ReviewError(
            "every review action needs an actor; an unattributed override is not an audit trail"
        )
    if not (reason or "").strip():
        raise ReviewError("every review action needs a reason")
    if action not in ACTIONS:
        raise ReviewError(
            f"unknown action {action!r}; known actions: {', '.join(sorted(ACTIONS))}"
        )

    entry = _entry(comparison, candidate)

    if action in FLAG_ACTIONS:
        if target not in _flag_ids(entry):
            raise ReviewError(
                f"{candidate} has no flag {target!r}; dismiss a flag by the flag_id "
                "shown in the dossier"
            )
    elif not (target or "").strip():
        raise ReviewError("a band override needs the band to record")

    if comparison.status == "reviewed":
        comparison.revision += 1
        comparison.status = "pending_review"
        comparison.approved_at = None

    return _append(
        session,
        comparison,
        actor=actor,
        action=action,
        reason=reason.strip(),
        entry_id=entry.id,
        target=target,
    )


def approve(session: Session, comparison: ComparisonRecord, actor: str) -> ReviewAction:
    actor = (actor or "").strip()
    if not actor:
        raise ReviewError("an approval needs a named actor")

    record = _append(
        session,
        comparison,
        actor=actor,
        action="approve",
        reason=f"approved revision {comparison.revision}",
        entry_id=None,
        target=None,
    )
    comparison.status = "reviewed"
    comparison.approved_at = _now()
    session.flush()
    return record


def dismissed_by_handle(
    session: Session, comparison: ComparisonRecord
) -> dict[str, frozenset[str]]:
    """Replay the log; the last action for a flag is the one that counts."""
    state: dict[str, dict[str, bool]] = {
        entry.candidate_handle: {} for entry in comparison.entries
    }
    by_id = {entry.id: entry.candidate_handle for entry in comparison.entries}

    for action in _actions(session, comparison):
        if action.action not in FLAG_ACTIONS or action.entry_id is None:
            continue
        handle = by_id.get(action.entry_id)
        if handle is None or action.target is None:
            continue
        state[handle][action.target] = action.action == "flag_dismiss"

    return {
        handle: frozenset(flag for flag, dropped in flags.items() if dropped)
        for handle, flags in state.items()
    }


def _overrides(session: Session, comparison: ComparisonRecord) -> dict[str, dict[str, str]]:
    by_id = {entry.id: entry.candidate_handle for entry in comparison.entries}
    overrides: dict[str, dict[str, str]] = {}
    for action in _actions(session, comparison):
        if action.action != "band_override" or action.entry_id is None:
            continue
        handle = by_id.get(action.entry_id)
        if handle is None:
            continue
        overrides[handle] = {"band": action.target or "", "reason": action.reason}
    return overrides


def effective_result(session: Session, comparison: ComparisonRecord) -> dict[str, Any]:
    rubric = load_rubric(session, comparison.rubric.name)
    payloads = [
        entry.dossier.payload for entry in sorted(comparison.entries, key=lambda e: e.id)
    ]
    result = compare(payloads, rubric, dismissed_by_handle(session, comparison))

    overrides = _overrides(session, comparison)
    machine = {entry.candidate_handle: entry.machine_score for entry in comparison.entries}

    heard = responses_by_handle(session, comparison)

    for row in result["ranked"]:
        handle = row["handle"]
        row["machine_score"] = machine.get(handle)
        override = overrides.get(handle)
        row["human_band"] = override["band"] if override else None
        row["override_reason"] = override["reason"] if override else None
        # Beside the machine result and the recruiter's overrides, never
        # folded into either. Weighing it is the reviewer's job.
        row["candidate_responses"] = heard.get(handle, [])

    for row in result.get("unranked") or []:
        row["candidate_responses"] = heard.get(row["handle"], [])

    result["status"] = comparison.status
    result["revision"] = comparison.revision
    return result


def audit_log(session: Session, comparison: ComparisonRecord) -> list[dict[str, Any]]:
    by_id = {entry.id: entry.candidate_handle for entry in comparison.entries}
    return [
        {
            "actor": action.actor,
            "action": action.action,
            "candidate": by_id.get(action.entry_id),
            "target": action.target,
            "reason": action.reason,
            "revision": action.revision,
            "created_at": action.created_at.isoformat(),
        }
        for action in _actions(session, comparison)
    ]


def export_payload(session: Session, comparison: ComparisonRecord) -> dict[str, Any]:
    if comparison.status != "reviewed":
        raise ReviewError(
            f"comparison {comparison.id} is pending_review at revision "
            f"{comparison.revision}; a named human must approve it before it can be "
            "exported"
        )

    payload = effective_result(session, comparison)
    payload["comparison_id"] = comparison.id
    payload["approved_at"] = (
        comparison.approved_at.isoformat() if comparison.approved_at else None
    )
    payload["audit_log"] = audit_log(session, comparison)
    payload["disclaimer"] = DISCLAIMER
    return payload


def record_response(
    session: Session,
    comparison: ComparisonRecord,
    *,
    candidate: str,
    text: str,
    recorded_by: str,
    flag_id: str | None = None,
) -> CandidateResponse:
    """Put the candidate's own account of a finding on the record.

    **It reopens the gate.** A rebuttal is information the approver did not
    have, and a comparison approved before hearing it was approved on a
    different set of facts. That is the whole point of recording it: an
    explanation nobody has to read before exporting is decoration.

    It never touches a score. The machine result stands, the recruiter's
    overrides stand, and this sits beside both, exactly as a dismissal does.
    Weighing it is the reviewer's job and always was.
    """
    text = (text or "").strip()
    if not text:
        raise ReviewError("a response with nothing in it is not a response")

    recorded_by = (recorded_by or "").strip()
    if not recorded_by:
        raise ReviewError(
            "say who took this down; a candidate has no account here, so the "
            "transcription needs an owner even though the words do not"
        )

    entry = _entry(comparison, candidate)
    if flag_id is not None and flag_id not in _flag_ids(entry):
        raise ReviewError(
            f"{candidate} has no flag {flag_id!r}; answer a flag by the flag_id "
            "shown in the dossier, or leave it out to answer the assessment"
        )

    if comparison.status == "reviewed":
        comparison.revision += 1
        comparison.status = "pending_review"
        comparison.approved_at = None

    record = CandidateResponse(
        comparison_id=comparison.id,
        candidate_handle=candidate,
        flag_id=flag_id,
        text=text,
        recorded_by=recorded_by,
        revision=comparison.revision,
        created_at=_now(),
    )
    session.add(record)
    session.flush()
    return record


def responses_by_handle(
    session: Session, comparison: ComparisonRecord
) -> dict[str, list[dict[str, Any]]]:
    """Every response this comparison has heard, in the order it heard them."""
    records = session.scalars(
        select(CandidateResponse)
        .where(CandidateResponse.comparison_id == comparison.id)
        .order_by(CandidateResponse.id)
    ).all()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.candidate_handle, []).append(
            {
                "flag_id": record.flag_id,
                "text": record.text,
                "recorded_by": record.recorded_by,
                "revision": record.revision,
                "created_at": record.created_at.isoformat(),
            }
        )
    return grouped

"""The shape the API emits, against the shape the dashboard expects.

The review screen and the API are developed apart and tested apart: the API
suite asserts what Python returns, and the interface suite asserts what React
does with hand-written objects. Nothing compared the two, so a renamed field
would pass both suites and break the one screen where a defect costs a hiring
decision.

This writes the real payload to a fixture the interface suite reads, and fails
when the committed fixture no longer matches what the API produces. Regenerate
it by running this test; the diff is the contract change.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_api import _seeded_client

FIXTURE = Path(__file__).resolve().parents[1] / "ui" / "src" / "test" / "contract.json"


#: Values that differ on every run. The contract is the shape, not the clock.
_VOLATILE = ("created_at", "stored_at", "approved_at", "finished_at", "generated_at")


def _normalised(value):
    """The same payload with wall-clock values replaced by a marker."""
    if isinstance(value, dict):
        return {
            key: ("<timestamp>" if key in _VOLATILE and item is not None else _normalised(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalised(item) for item in value]
    return value

def _live_payload(tmp_path, monkeypatch) -> dict:
    """One comparison, reviewed and approved, as the API actually returns it."""
    from veriquill.rubric import DIMENSIONS

    client = _seeded_client(tmp_path, monkeypatch)
    client.post("/rubrics", json={"name": "backend", "weights": {d: 1.0 for d in DIMENSIONS}})
    created = client.post("/comparisons", json={"rubric": "backend", "candidates": ["alpha"]})
    comparison_id = created.json()["comparison_id"]

    # Exercise the human half too, so the fixture carries the override fields
    # rather than only the machine ones.
    client.post(
        f"/comparisons/{comparison_id}/review",
        json={
            "actor": "reviewer@example.com",
            "action": "flag_dismiss",
            "candidate": "alpha",
            "target": "abc",
            "reason": "employer-owned import",
        },
    )
    client.post(
        f"/comparisons/{comparison_id}/approve", json={"actor": "reviewer@example.com"}
    )

    return {
        "comparison": client.get(f"/comparisons/{comparison_id}").json()["result"],
        "audit": client.get(f"/comparisons/{comparison_id}/audit").json()["audit_log"],
        "candidates": client.get("/candidates").json()["candidates"],
    }


def test_the_committed_contract_matches_what_the_api_returns(tmp_path, monkeypatch):
    """A stale fixture means the interface suite is testing a shape that is gone."""
    payload = _live_payload(tmp_path, monkeypatch)
    rendered = json.dumps(_normalised(payload), indent=2, sort_keys=True, default=str) + "\n"

    if not FIXTURE.exists() or FIXTURE.read_text(encoding="utf-8") != rendered:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(rendered, encoding="utf-8")
        raise AssertionError(
            f"{FIXTURE.name} was regenerated because the API's shape changed. "
            "Review the diff, run the interface suite against it, and commit both."
        )


def test_the_contract_carries_what_the_review_screen_reads(tmp_path, monkeypatch):
    """Named explicitly, so dropping one is a failure here and not a blank panel."""
    payload = _live_payload(tmp_path, monkeypatch)
    result = payload["comparison"]

    assert {"ranked", "unranked", "status", "revision", "disclaimer"} <= set(result)
    assert result["status"] in {"pending_review", "reviewed"}

    row = result["ranked"][0]
    assert {"handle", "rank", "tie_group", "score", "drivers"} <= set(row)

    score = row["score"]
    assert {
        "handle",
        "score",
        "band",
        "width",
        "confidence",
        "coverage",
        "dimensions",
        "unmeasured",
        "bar_breaches",
    } <= set(score)
    assert len(score["band"]) == 2

    dimension = score["dimensions"][0]
    assert {"dimension", "score", "coverage", "basis", "evidence"} <= set(dimension)

    entry = payload["audit"][0]
    assert {"actor", "action", "candidate", "reason", "revision", "created_at"} <= set(entry)

"""Who is calling, and whether the audit log can be believed.

The review gate promises that replaying its rows reconstructs any state a
comparison has held. That promise was hollow while the actor was a string in the
request body: anyone could sign an override with anyone's name, and the log
recorded a claim rather than a fact.

These tests hold the two halves of the fix. Configured keys must bind the actor
to the key. No keys must leave the server open, because that is what a local run
and this suite need, and the server has to say so rather than let it be found.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from veriquill.api.auth import ANONYMOUS, Identity, actor_for, resolve, warn_if_open
from veriquill.api.main import app
from veriquill.config import Settings, get_settings

KEY = "sk_test_abcdefghijklmnop"
OTHER = "sk_test_zzzzzzzzzzzzzzzz"


class _Request:
    """The slice of Request that `resolve` reads."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def _settings(tmp_path, keys=None) -> Settings:
    return Settings(data_dir=tmp_path, api_keys=keys or {})


def _client(tmp_path, monkeypatch, keys=None) -> TestClient:
    from veriquill.api import main as api_main

    get_settings.cache_clear()
    settings = Settings(data_dir=tmp_path / ".veriquill", api_keys=keys or {})
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    monkeypatch.setattr("veriquill.api.auth.get_settings", lambda: settings)
    settings.ensure_dirs()
    return TestClient(app)


def test_with_no_keys_the_server_is_open(tmp_path):
    assert resolve(_Request(), _settings(tmp_path)) is ANONYMOUS


def test_an_open_server_says_so(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert warn_if_open(_settings(tmp_path)) is True

    assert "open" in caplog.text.lower()


def test_a_server_with_keys_does_not_warn(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert warn_if_open(_settings(tmp_path, {KEY: "alice"})) is False

    assert caplog.text == ""


def test_a_valid_bearer_key_identifies_the_caller(tmp_path):
    identity = resolve(
        _Request({"authorization": f"Bearer {KEY}"}), _settings(tmp_path, {KEY: "alice"})
    )

    assert identity.actor == "alice"
    assert identity.authenticated


def test_the_x_api_key_header_works_too(tmp_path):
    identity = resolve(_Request({"x-api-key": KEY}), _settings(tmp_path, {KEY: "alice"}))

    assert identity.actor == "alice"


def test_a_missing_key_is_refused_when_keys_are_configured(tmp_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        resolve(_Request(), _settings(tmp_path, {KEY: "alice"}))

    assert exc.value.status_code == 401


def test_an_unknown_key_is_refused(tmp_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        resolve(_Request({"authorization": f"Bearer {OTHER}"}), _settings(tmp_path, {KEY: "alice"}))

    assert exc.value.status_code == 401


def test_a_malformed_authorization_header_is_refused(tmp_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        resolve(_Request({"authorization": KEY}), _settings(tmp_path, {KEY: "alice"}))


def test_an_authenticated_actor_comes_from_the_key():
    identity = Identity(actor="alice@example.com", authenticated=True)

    assert actor_for(identity, "") == "alice@example.com"
    assert actor_for(identity, None) == "alice@example.com"


def test_an_authenticated_caller_cannot_sign_as_someone_else():
    """The whole point: the log records a fact, not a claim."""
    from fastapi import HTTPException

    identity = Identity(actor="alice@example.com", authenticated=True)

    with pytest.raises(HTTPException) as exc:
        actor_for(identity, "bob@example.com")

    assert exc.value.status_code == 403


def test_naming_yourself_is_allowed_since_it_asserts_nothing_extra():
    identity = Identity(actor="alice@example.com", authenticated=True)

    assert actor_for(identity, "alice@example.com") == "alice@example.com"


def test_an_anonymous_actor_is_whatever_was_typed():
    assert actor_for(ANONYMOUS, "  whoever  ") == "whoever"


def test_health_answers_without_a_key(tmp_path, monkeypatch):
    """A liveness probe cannot be expected to hold credentials."""
    client = _client(tmp_path, monkeypatch, {KEY: "alice"})

    assert client.get("/health").status_code == 200


def test_an_endpoint_refuses_an_unkeyed_request(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {KEY: "alice"})

    response = client.get("/candidates")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_an_endpoint_accepts_a_keyed_request(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {KEY: "alice"})

    response = client.get("/candidates", headers={"Authorization": f"Bearer {KEY}"})

    assert response.status_code == 200


def test_the_api_prefix_is_protected_too(tmp_path, monkeypatch):
    """Both mountings are the same router, so a gap in one would be a gap in both."""
    client = _client(tmp_path, monkeypatch, {KEY: "alice"})

    assert client.get("/api/candidates").status_code == 401


def test_without_keys_every_endpoint_stays_reachable(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    assert client.get("/candidates").status_code == 200


def test_a_review_action_is_signed_by_the_key_not_the_body(tmp_path, monkeypatch):
    """An override recorded under someone else's name is the thing to prevent."""
    from tests.test_api import _seeded_comparison

    client, comparison_id = _seeded_comparison(tmp_path, monkeypatch, keys={KEY: "alice@example.com"})

    refused = client.post(
        f"/comparisons/{comparison_id}/approve",
        json={"actor": "bob@example.com"},
        headers={"Authorization": f"Bearer {KEY}"},
    )

    assert refused.status_code == 403
    assert "alice@example.com" in refused.json()["detail"]


def test_an_approval_with_no_actor_is_signed_by_the_key(tmp_path, monkeypatch):
    from tests.test_api import _seeded_comparison

    client, comparison_id = _seeded_comparison(tmp_path, monkeypatch, keys={KEY: "alice@example.com"})

    approved = client.post(
        f"/comparisons/{comparison_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {KEY}"},
    )
    assert approved.status_code == 200

    log = client.get(
        f"/comparisons/{comparison_id}/audit", headers={"Authorization": f"Bearer {KEY}"}
    ).json()
    actors = {row["actor"] for row in log["audit_log"]}

    assert actors == {"alice@example.com"}

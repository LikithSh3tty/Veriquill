"""When a model is allowed to run at all.

Both optional passes cost money and send a candidate's material to a third
party. Neither should ever start doing that because a key happened to be
present in the environment, so all three conditions have to hold: the feature
is switched on, the optional SDK is installed, and credentials resolve.
"""

from __future__ import annotations

import builtins

import pytest

from veriquill.config import Settings
from veriquill.llm import build_client


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(data_dir=tmp_path, **overrides)


def test_both_model_passes_are_off_unless_asked_for(tmp_path):
    settings = _settings(tmp_path)

    assert settings.claim_refinement_enabled is False
    assert settings.code_review_enabled is False


def test_a_disabled_feature_builds_no_client(tmp_path):
    assert build_client(_settings(tmp_path), enabled=False, purpose="claim refinement") is None


def test_a_missing_optional_sdk_disables_rather_than_raises(tmp_path, monkeypatch):
    """`anthropic` is an optional dependency; without it the pass is skipped."""
    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)

    settings = _settings(tmp_path, anthropic_api_key="sk-ant-test")
    assert build_client(settings, enabled=True, purpose="design review") is None


def test_the_key_from_settings_is_what_reaches_the_sdk(tmp_path, monkeypatch):
    """The point of the setting: `.env` genuinely controls this."""
    import anthropic

    seen = {}

    def capture(*_args, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(anthropic, "Anthropic", capture)

    settings = _settings(tmp_path, anthropic_api_key="sk-ant-from-dotenv")
    client = build_client(settings, enabled=True, purpose="claim refinement")

    assert client is not None
    assert seen["api_key"] == "sk-ant-from-dotenv"


def test_without_a_configured_key_the_sdk_resolves_its_own(tmp_path, monkeypatch):
    """An unset key is not proof there are none: a logged-in profile also counts."""
    import anthropic

    seen = {}

    def capture(*_args, **kwargs):
        seen["called_with"] = kwargs
        return object()

    monkeypatch.setattr(anthropic, "Anthropic", capture)

    build_client(_settings(tmp_path), enabled=True, purpose="claim refinement")

    assert seen["called_with"] == {}


def test_unresolvable_credentials_disable_rather_than_raise(tmp_path, monkeypatch):
    import anthropic

    def refuse(*_args, **_kwargs):
        raise TypeError("Could not resolve authentication method")

    monkeypatch.setattr(anthropic, "Anthropic", refuse)

    assert build_client(_settings(tmp_path), enabled=True, purpose="design review") is None


def test_a_blank_key_falls_through_to_the_sdk(tmp_path, monkeypatch):
    import anthropic

    seen = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: seen.update(k) or object())

    build_client(_settings(tmp_path, anthropic_api_key="   "), enabled=True, purpose="x")

    assert "api_key" not in seen


@pytest.mark.parametrize("enabled", [True, False])
def test_nothing_here_ever_raises(tmp_path, enabled, monkeypatch):
    """A missing optional feature must never be able to fail an analysis."""
    import anthropic

    monkeypatch.setattr(
        anthropic, "Anthropic", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert build_client(_settings(tmp_path), enabled=enabled, purpose="x") is None

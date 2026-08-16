from pathlib import Path

from veriquill.config import Settings


def test_paths_derive_from_data_dir(tmp_path: Path):
    settings = Settings(github_token="t", data_dir=tmp_path)
    assert settings.cache_dir == tmp_path / "cache"
    assert settings.workdir == tmp_path / "workdir"
    assert settings.db_path == tmp_path / "veriquill.sqlite"


def test_token_is_not_exposed_in_repr(tmp_path: Path):
    settings = Settings(github_token="super-secret-token", data_dir=tmp_path)
    assert "super-secret-token" not in repr(settings)


def test_thresholds_have_documented_defaults(tmp_path: Path):
    settings = Settings(github_token="t", data_dir=tmp_path)
    assert settings.burst_window_seconds == 60
    assert settings.burst_min_commits == 10
    assert settings.rate_limit_floor == 100

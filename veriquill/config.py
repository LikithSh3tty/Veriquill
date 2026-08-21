"""Runtime settings.

Thresholds are tunable and documented. They are calibrated for precision:
a false accusation costs a real candidate far more than a missed flag costs
a recruiter.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERIQUILL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: SecretStr = SecretStr("")
    api_base_url: str = "https://api.github.com"
    data_dir: Path = Path(".veriquill")
    ui_dist: Path = Field(
        default=Path("ui/dist"),
        description=(
            "Built interface served at the root. Absent in a checkout that has "
            "not run the frontend build, in which case only the API is served."
        ),
    )

    # Claim refinement (optional; the structural parsers always run without it)
    claim_model: str = Field(
        default="claude-opus-5",
        description="Model used to phrase claims the structural parser missed.",
    )
    claim_refinement_enabled: bool = True
    claim_max_tokens: int = 16000

    # Optional design review (off by default; every metric stays deterministic)
    code_review_enabled: bool = Field(
        default=False,
        description=(
            "Let a model phrase design judgment over authored Python. It cites "
            "or is discarded, and never reports a metric."
        ),
    )
    code_review_model: str = "claude-sonnet-5"
    code_review_max_tokens: int = 8000

    # Reading a large account in part (relevance.py)
    relevance_threshold: int = Field(
        default=20,
        description=(
            "Accounts with more repositories than this are read in part, "
            "most-relevant first. Smaller accounts are always read in full."
        ),
    )
    relevance_limit: int = Field(
        default=5,
        description="How many repositories to read when an account is over the threshold.",
    )

    # Rate limiting
    rate_limit_floor: int = Field(
        default=100,
        description="Pause until reset when remaining quota drops below this.",
    )
    max_retry_attempts: int = 5

    # Concurrency and timeouts
    max_clone_concurrency: int = 4
    clone_timeout_seconds: int = 300
    analyser_timeout_seconds: int = 120

    # Provenance thresholds
    burst_window_seconds: int = Field(
        default=60,
        description="Window used to detect scripted commit bursts.",
    )
    burst_min_commits: int = Field(
        default=10,
        description="Commits inside one window before cadence is flagged.",
    )
    bulk_dump_loc_share: float = Field(
        default=0.8,
        description="Share of total inserted lines landing in the first commit.",
    )
    bulk_dump_min_loc: int = Field(
        default=1000,
        description="Repositories smaller than this are too small to judge.",
    )
    fork_min_total_loc: int = Field(
        default=200,
        description=(
            "Repositories smaller than this are too trivial for the fork check. "
            "Calling a 40-line repository 'a fork presented as original' is "
            "technically true and practically an overstatement."
        ),
    )
    inflation_authored_share: float = Field(
        default=0.25,
        description="Flag when authored lines fall below this share of total.",
    )
    inflation_min_total_loc: int = 2000
    duplication_jaccard: float = Field(
        default=0.8,
        description="File-hash overlap above which two repositories match.",
    )
    contribution_low_share: float = Field(
        default=0.2,
        description="Flag when the candidate authored below this share of commits.",
    )

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def workdir(self) -> Path:
        return self.data_dir / "workdir"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "veriquill.sqlite"

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.workdir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
